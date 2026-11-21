"""Rebuild `professions_data/professions.json`, the committed professions snapshot.

Sources (all fetched here, nothing at runtime):
- ILO GenAI exposure 2025, Gmyrek et al. (WP140), CC BY 4.0, ISCO-08 4-digit
  occupation mean task score `mean_score_2025`:
  https://github.com/pgmyrek/2025_GenAI_scores_ISCO08
- English names: ESCO API, ISCO-08 concepts (no Russian or Uzbek there):
  https://ec.europa.eu/esco/api
- Russian and Uzbek names: translated in-house (table below), marked as such.

Risk follows `ikigai-research`: R = E x (0.5 + 0.5 S) with E the score divided by
the maximum of the ILO table and S = 0.5 (no usage data joined); bands low
<0.25, medium 0.25..0.5, high >0.5. The horizon is a derived scenario from the
ILO exposure gradient, never a calendar year.

Run: `uv run python scripts/build_professions_snapshot.py`.
"""

import concurrent.futures as cf
import io
import json
import subprocess
from datetime import date
from pathlib import Path

import openpyxl

from app.modules.admission.domain.professions import (
    MAJOR_GROUPS,
    SCORE_MAX,
    horizon_of,
    risk_of,
)
from app.modules.admission.domain.study_fields import FIELDS

ILO_XLSX = (
    "https://raw.githubusercontent.com/pgmyrek/2025_GenAI_scores_ISCO08/main/"
    "Final_Scores_ISCO08_Gmyrek_et_al_2025.xlsx"
)
ESCO = (
    "https://ec.europa.eu/esco/api/resource/concept"
    "?uri=http://data.europa.eu/esco/isco/C{code}&language=en"
)
OUT = (
    Path(__file__).resolve().parent.parent
    / "app/modules/admission/infrastructure/professions_data/professions.json"
)

# code | ru | uz | study-field ids
ROWS = """
1120|Генеральный директор|Bosh direktor|management,business,entrepreneurship
1211|Финансовый директор|Moliya direktori|finance,accounting,business
1212|Руководитель по персоналу|Kadrlar boʻyicha rahbar|management,psychology
1213|Руководитель по стратегии и планированию|Strategiya va rejalashtirish rahbari|management,economics
1221|Руководитель по продажам и маркетингу|Savdo va marketing rahbari|marketing,business
1222|Руководитель по рекламе и PR|Reklama va PR rahbari|marketing,communications
1223|Руководитель исследований и разработок|Tadqiqot va ishlanmalar rahbari|engineering,natural_sciences,management
1321|Руководитель производства|Ishlab chiqarish rahbari|industrial_engineering,management
1323|Руководитель строительства|Qurilish rahbari|civil_engineering,management
1330|Руководитель ИТ-службы|AKT xizmati rahbari|computer_science,information_systems,management
1342|Руководитель в здравоохранении|Sogʻliqni saqlash rahbari|public_health,management
1345|Руководитель образовательной организации|Taʼlim muassasasi rahbari|education,management
2111|Физик и астроном|Fizik va astronom|physics,astronomy
2112|Метеоролог|Meteorolog|earth_sciences,physics
2113|Химик|Kimyogar|chemistry,biochemistry
2114|Геолог и геофизик|Geolog va geofizik|earth_sciences,geography
2120|Математик, актуарий, статистик|Matematik, aktuariy, statistik|mathematics,statistics
2131|Биолог, ботаник, зоолог|Biolog, botanik, zoolog|biology,marine_biology
2132|Консультант по сельскому и лесному хозяйству|Qishloq va oʻrmon xoʻjaligi maslahatchisi|agriculture,environmental_science
2133|Специалист по охране окружающей среды|Atrof-muhitni muhofaza qilish mutaxassisi|environmental_science
2141|Инженер по организации производства|Ishlab chiqarishni tashkil etish muhandisi|industrial_engineering,engineering
2142|Инженер-строитель|Qurilish muhandisi|civil_engineering,engineering
2143|Инженер-эколог|Ekolog muhandis|environmental_science,engineering
2144|Инженер-механик|Muhandis-mexanik|mechanical_engineering,engineering
2145|Инженер-химик|Muhandis-kimyogar|chemical_engineering,chemistry
2146|Горный инженер и металлург|Togʻ-kon muhandisi va metallurg|petroleum_engineering,materials_engineering
2149|Инженер (прочие специальности)|Muhandis (boshqa yoʻnalishlar)|engineering,aerospace_engineering,nuclear_engineering
2151|Инженер-электрик|Muhandis-elektrik|electrical_engineering,engineering
2152|Инженер-электронщик|Muhandis-elektronchi|electrical_engineering,engineering
2153|Инженер по телекоммуникациям|Telekommunikatsiya muhandisi|electrical_engineering,computer_science
2161|Архитектор|Arxitektor|architecture
2162|Ландшафтный архитектор|Landshaft arxitektori|architecture,environmental_science
2163|Промышленный дизайнер и дизайнер одежды|Sanoat va kiyim dizayneri|design,fashion
2164|Градостроитель и транспортный планировщик|Shaharsozlik va transport rejalashtiruvchisi|urban_planning,architecture
2165|Картограф и геодезист|Kartograf va geodezist|geography,earth_sciences
2166|Графический дизайнер и мультимедиа-дизайнер|Grafik va multimedia dizayner|graphic_design,design,media_studies
2211|Врач общей практики|Umumiy amaliyot shifokori|medicine
2212|Врач-специалист|Mutaxassis shifokor|medicine,neuroscience
2221|Медицинская сестра (специалист)|Hamshira (mutaxassis)|nursing
2222|Акушер|Akusher|nursing,medicine
2250|Ветеринар|Veterinar|veterinary,biology
2261|Стоматолог|Stomatolog|dentistry
2262|Фармацевт|Farmatsevt|pharmacy,chemistry
2263|Специалист по гигиене и охране здоровья на труде|Gigiyena va mehnat salomatligi mutaxassisi|public_health
2264|Физиотерапевт|Fizioterapevt|kinesiology,medicine
2265|Диетолог и нутрициолог|Dietolog va nutritsiolog|nutrition,food_science
2266|Аудиолог и логопед|Audiolog va logoped|medicine,psychology,linguistics
2267|Оптометрист|Optometrist|medicine
2269|Специалист здравоохранения (прочие)|Sogʻliqni saqlash mutaxassisi (boshqa)|public_health,biology
2310|Преподаватель университета|Universitet oʻqituvchisi|education,liberal_arts
2320|Преподаватель профессионального обучения|Kasb-hunar taʼlimi oʻqituvchisi|education
2330|Учитель средней школы|Umumiy oʻrta taʼlim oʻqituvchisi|education
2341|Учитель начальной школы|Boshlangʻich sinf oʻqituvchisi|education
2342|Воспитатель детского сада|Maktabgacha taʼlim tarbiyachisi|education,psychology
2351|Методист в образовании|Taʼlim metodisti|education
2352|Учитель для детей с особыми потребностями|Maxsus ehtiyojli bolalar oʻqituvchisi|education,psychology
2353|Преподаватель иностранных языков|Chet tili oʻqituvchisi|linguistics,literature_languages,education
2354|Преподаватель музыки|Musiqa oʻqituvchisi|music_performing,education
2355|Преподаватель искусства|Sanʼat oʻqituvchisi|arts,education
2356|Тренер по информационным технологиям|AKT boʻyicha trener|computer_science,education
2411|Бухгалтер|Buxgalter|accounting,finance
2412|Финансовый и инвестиционный консультант|Moliyaviy va investitsiya maslahatchisi|finance,economics
2413|Финансовый аналитик|Moliyaviy tahlilchi|finance,economics,statistics
2421|Аналитик по управлению и организации|Boshqaruv va tashkilot tahlilchisi|management,business
2422|Специалист по государственной политике|Davlat siyosati mutaxassisi|politics,economics
2423|Специалист по персоналу и карьере|Kadrlar va karyera mutaxassisi|psychology,management
2424|Специалист по обучению персонала|Xodimlarni oʻqitish mutaxassisi|education,management
2431|Специалист по рекламе и маркетингу|Reklama va marketing mutaxassisi|marketing,communications
2432|Специалист по связям с общественностью|Jamoatchilik bilan aloqa mutaxassisi|communications,media_studies
2433|Менеджер по техническим и медицинским продажам|Texnik va tibbiy savdo menejeri|business,marketing
2434|Менеджер по продажам ИКТ|AKT savdo menejeri|business,computer_science
2511|Системный аналитик|Tizim tahlilchisi|information_systems,computer_science
2512|Разработчик программного обеспечения|Dasturiy taʼminot dasturchisi|software_engineering,computer_science
2513|Веб- и мультимедиа-разработчик|Veb va multimedia dasturchisi|software_engineering,computer_science,design
2514|Прикладной программист|Amaliy dasturchi|software_engineering,computer_science
2519|Разработчик и аналитик ПО (прочие)|Dasturiy taʼminot tahlilchisi (boshqa)|software_engineering,data_science,game_design
2521|Проектировщик и администратор баз данных|Maʼlumotlar bazasi loyihachisi va administratori|information_systems,data_science
2522|Системный администратор|Tizim administratori|information_systems,cybersecurity
2523|Специалист по компьютерным сетям|Kompyuter tarmoqlari mutaxassisi|computer_science,cybersecurity
2529|Специалист по базам данных и сетям (прочие)|Maʼlumotlar bazasi va tarmoq mutaxassisi (boshqa)|cybersecurity,data_science
2611|Юрист|Yurist|law
2612|Судья|Sudya|law
2619|Юрист (прочие специальности)|Huquqshunos (boshqa)|law,criminology
2621|Архивист и куратор|Arxivchi va kurator|history,humanities
2622|Библиотекарь и информационный специалист|Kutubxonachi va axborot mutaxassisi|humanities,information_systems
2631|Экономист|Iqtisodchi|economics,statistics
2632|Социолог и антрополог|Sotsiolog va antropolog|sociology,anthropology,social_sciences
2633|Философ, историк, политолог|Faylasuf, tarixchi, siyosatshunos|philosophy,history,politics
2634|Психолог|Psixolog|psychology,cognitive_science,neuroscience
2635|Социальный работник и консультант|Ijtimoiy ishchi va maslahatchi|social_work,psychology
2641|Автор и писатель|Muallif va yozuvchi|creative_writing,literature_languages
2642|Журналист|Jurnalist|journalism,communications
2643|Переводчик и лингвист|Tarjimon va tilshunos|linguistics,literature_languages
2651|Художник|Rassom|arts,design
2652|Музыкант, певец, композитор|Musiqachi, qoʻshiqchi, kompozitor|music_performing
2653|Танцор и хореограф|Raqqosa va xoreograf|dance
2654|Режиссёр и продюсер|Rejissyor va prodyuser|film,theatre,media_studies
2655|Актёр|Aktyor|theatre,film
2656|Диктор и ведущий|Diktor va boshlovchi|media_studies,communications
2659|Творческий работник (прочие)|Ijodiy xodim (boshqa)|arts,film,game_design
3111|Лаборант по химии и физике|Kimyo va fizika laboranti|chemistry,physics
3112|Техник-строитель|Qurilish texnigi|civil_engineering
3113|Техник-электрик|Elektrik texnik|electrical_engineering
3114|Техник-электронщик|Elektronika texnigi|electrical_engineering
3115|Техник-механик|Mexanik texnik|mechanical_engineering
3116|Техник-химик|Kimyo texnigi|chemical_engineering
3117|Техник горный и металлургический|Togʻ-kon va metallurgiya texnigi|materials_engineering
3118|Чертёжник|Chizmachi|architecture,engineering
3119|Технический специалист (прочие)|Texnik mutaxassis (boshqa)|engineering
3141|Лаборант по биологии|Biologiya laboranti|biology,biochemistry
3151|Судовой механик|Kema mexanigi|mechanical_engineering
3152|Штурман и лоцман|Kema shturmani va lotsman|aviation,engineering
3153|Пилот|Uchuvchi|aviation,aerospace_engineering
3154|Авиадиспетчер|Aviadispetcher|aviation
3211|Техник по медицинской визуализации|Tibbiy tasvirlash texnigi|medicine,biomedical_engineering
3212|Лаборант медицинской диагностики|Tibbiy laborant|medicine,biochemistry
3221|Медицинская сестра|Hamshira|nursing
3253|Работник общественного здравоохранения|Jamoat salomatligi xodimi|public_health,nursing
3256|Помощник врача|Shifokor yordamchisi|medicine,nursing
3257|Инспектор по гигиене и охране труда|Gigiyena va mehnat muhofazasi inspektori|public_health,environmental_science
3311|Брокер и дилер ценных бумаг|Qimmatli qogʻozlar brokeri va dilleri|finance,economics
3312|Кредитный специалист|Kredit mutaxassisi|finance
3313|Помощник бухгалтера|Buxgalter yordamchisi|accounting
3314|Специалист по статистике|Statistika mutaxassisi|statistics,mathematics
3315|Оценщик и эксперт по убыткам|Baholovchi va zarar eksperti|finance,real_estate
3321|Страховой агент|Sugʻurta agenti|finance,business
3322|Торговый представитель|Savdo vakili|business,marketing
3323|Закупщик|Xaridor-menejer|supply_chain,business
3324|Торговый брокер|Savdo brokeri|business,supply_chain
3331|Таможенный и экспедиторский агент|Bojxona va ekspeditorlik agenti|supply_chain,international_relations
3332|Организатор мероприятий|Tadbirlar tashkilotchisi|hospitality,communications
3333|Агент по трудоустройству|Bandlik agenti|management,psychology
3334|Агент по недвижимости|Koʻchmas mulk agenti|real_estate
3343|Административный секретарь|Maʼmuriy kotib|management,business
3351|Таможенный и пограничный инспектор|Bojxona va chegara inspektori|law,international_relations
3352|Налоговый инспектор|Soliq inspektori|taxation,accounting
3355|Следователь и детектив|Tergovchi va detektiv|criminology,law
3412|Помощник социального работника|Ijtimoiy ishchi yordamchisi|social_work
3421|Спортсмен|Sportchi|kinesiology,sports_management
3422|Тренер и спортивный судья|Murabbiy va sport hakami|kinesiology,sports_management
3423|Фитнес-инструктор|Fitnes instruktori|kinesiology,nutrition
3431|Фотограф|Fotograf|arts,media_studies,film
3432|Дизайнер интерьера|Interer dizayneri|design,architecture
3433|Технический сотрудник музея и библиотеки|Muzey va kutubxona texnik xodimi|humanities,arts
3434|Шеф-повар|Bosh oshpaz|hospitality,food_science
3511|Техник по эксплуатации ИКТ|AKT operatsiyalari texnigi|information_systems,cybersecurity
3512|Техник поддержки пользователей ИКТ|AKT foydalanuvchilarni qoʻllab-quvvatlash texnigi|information_systems
3513|Техник по сетям и системам|Tarmoq va tizim texnigi|computer_science,cybersecurity
3514|Веб-техник|Veb texnik|computer_science,software_engineering
3521|Техник по вещанию и аудиовизуальной технике|Eshittirish va audiovizual texnika texnigi|media_studies,film
3522|Техник по телекоммуникациям|Telekommunikatsiya texnigi|electrical_engineering
""".strip().splitlines()


def _fetch(url: str) -> bytes:
    """GET through curl (the system trust store; python's bundle may lack it)."""
    return subprocess.run(
        ["curl", "-fsSL", "--max-time", "120", url], check=True, capture_output=True
    ).stdout


def _score(workbook: openpyxl.Workbook) -> dict[str, tuple[float, str]]:
    ws = workbook.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    head = {name: i for i, name in enumerate(next(rows))}
    out: dict[str, tuple[float, str]] = {}
    for r in rows:
        out[str(r[head["ISCO_08"]])] = (
            float(r[head["mean_score_2025"]]),
            str(r[head["potential25"]]),
        )
    return out


def _english(code: str) -> str:
    return str(json.loads(_fetch(ESCO.format(code=code)))["preferredLabel"]["en"])


def main() -> None:
    """Fetch, merge and write the snapshot."""
    wb = openpyxl.load_workbook(io.BytesIO(_fetch(ILO_XLSX)), read_only=True)
    scores = _score(wb)
    assert max(v for v, _ in scores.values()) == SCORE_MAX
    valid = {f.id for f in FIELDS}
    table = [r.split("|") for r in ROWS]
    codes = [r[0] for r in table]
    with cf.ThreadPoolExecutor(8) as pool:
        english = dict(zip(codes, pool.map(_english, codes), strict=True))
    items = []
    for code, ru, uz, fields in table:
        rel = fields.split(",")
        assert set(rel) <= valid, (code, set(rel) - valid)
        score, gradient = scores[code]
        items.append(
            {
                "id": code,
                "group": code[0],
                "name": {"en": english[code], "ru": ru, "uz": uz},
                "ai_exposure": round(score, 2),
                "gradient": gradient,
                "ai_risk": risk_of(score),
                "horizon": horizon_of(score, gradient),
                "related_fields": rel,
            }
        )
    doc = {
        "retrieved": date.today().isoformat(),
        "sources": {
            "exposure": {
                "label": "ILO GenAI exposure 2025 (Gmyrek et al., WP140), CC BY 4.0",
                "url": "https://github.com/pgmyrek/2025_GenAI_scores_ISCO08",
            },
            "names_en": {
                "label": "ESCO ISCO-08 concepts, European Commission",
                "url": "https://ec.europa.eu/esco/api",
            },
            "names_ru_uz": {
                "label": "In-house translation of the ISCO-08 titles (ru, uz)",
                "url": "https://isco.ilo.org/",
            },
        },
        "groups": {k: dict(v) for k, v in MAJOR_GROUPS.items()},
        "items": items,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"{len(items)} professions -> {OUT}")


if __name__ == "__main__":
    main()
