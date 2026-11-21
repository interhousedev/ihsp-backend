"""Localised lines of the fit axes (`why` and `raise`), uz / ru / en."""

from typing import Final

LANGS: Final = ("en", "ru", "uz")
_COPY: Final[dict[str, tuple[str, str, str]]] = {
    "afford.within": (
        "Costs about {net} a year after aid, within your budget of {budget}",
        "Около {net} в год с учётом помощи, в рамках вашего бюджета {budget}",
        "Yordamdan keyin yiliga taxminan {net}, byudjetingiz {budget} doirasida",
    ),
    "afford.over": (
        "Costs about {net} a year after aid, above your budget of {budget}",
        "Около {net} в год с учётом помощи, выше вашего бюджета {budget}",
        "Yordamdan keyin yiliga taxminan {net}, byudjetingiz {budget}dan yuqori",
    ),
    "afford.open": (
        "Your budget has no upper limit; the cost is about {net} a year",
        "У вашего бюджета нет верхней границы; стоимость около {net} в год",
        "Byudjetingizning yuqori chegarasi yoʻq; narx yiliga taxminan {net}",
    ),
    "afford.sticker": (
        "No aid average is published, so the full price is used",
        "Средняя помощь не опубликована, поэтому берётся полная цена",
        "Oʻrtacha yordam eʼlon qilinmagan, shuning uchun toʻliq narx olindi",
    ),
    "afford.no_budget": (
        "Your family budget is not set",
        "Бюджет семьи не указан",
        "Oilaviy byudjet kiritilmagan",
    ),
    "afford.no_cost": (
        "The yearly cost in US dollars is not published",
        "Годовая стоимость в долларах США не опубликована",
        "Yillik narx AQSH dollarida eʼlon qilinmagan",
    ),
    "raise.afford.aid": (
        "Look at scholarships and aid",
        "Посмотрите стипендии и помощь",
        "Stipendiya va yordamni koʻring",
    ),
    "raise.afford.budget": (
        "State your family budget",
        "Укажите бюджет семьи",
        "Oilaviy byudjetni kiriting",
    ),
    "goals.match": (
        "Teaches {fields}, which leads to {profession}",
        "Есть {fields}: путь к профессии «{profession}»",
        "{fields} mavjud: «{profession}» kasbiga yoʻl",
    ),
    "goals.none": (
        "Its fields do not match the professions you chose",
        "Направления не совпадают с выбранными профессиями",
        "Yoʻnalishlar tanlangan kasblarga mos kelmaydi",
    ),
    "goals.risk": (
        "The matching professions have {risk} AI exposure",
        "У подходящих профессий {risk} подверженность ИИ",
        "Mos kasblarning SI taʼsiri {risk}",
    ),
    "goals.field": (
        "Based on your study fields; no professions chosen yet",
        "По вашим направлениям обучения; профессии ещё не выбраны",
        "Oʻqish yoʻnalishlaringiz asosida; kasblar hali tanlanmagan",
    ),
    "goals.no_fields": (
        "The university's fields of study are not listed",
        "Направления университета не указаны",
        "Universitet yoʻnalishlari koʻrsatilmagan",
    ),
    "goals.salary": (
        "Pay band of the matching professions: {band}",
        "Уровень оплаты подходящих профессий: {band}",
        "Mos kasblar maoshi darajasi: {band}",
    ),
    "raise.goals.pick": (
        "Choose the professions you want",
        "Выберите профессии, которые вам интересны",
        "Oʻzingizga qiziq kasblarni tanlang",
    ),
    "profile.fields_yes": (
        "Offers {fields}, which you want to study",
        "Есть {fields}, которые вы хотите изучать",
        "Siz oʻqimoqchi boʻlgan {fields} mavjud",
    ),
    "profile.fields_group": (
        "Offers programmes in the same area as your fields",
        "Есть программы в той же области, что ваши направления",
        "Yoʻnalishlaringiz bilan bir sohada dasturlar bor",
    ),
    "profile.fields_no": (
        "Does not list the fields you want to study",
        "Не указаны направления, которые вы хотите изучать",
        "Siz oʻqimoqchi boʻlgan yoʻnalishlar koʻrsatilmagan",
    ),
    "profile.safety": (
        "Admission chances look safe for this university",
        "Шансы поступления высокие",
        "Qabul qilinish imkoniyati yuqori",
    ),
    "profile.target": (
        "Admission is a realistic target",
        "Поступление реалистично",
        "Qabul qilinish real maqsad",
    ),
    "profile.reach": (
        "Admission is a stretch: the acceptance rate is low",
        "Поступить сложно: низкий процент приёма",
        "Qabul qiyin: qabul foizi past",
    ),
    "profile.tests_missing": (
        "Test scores are required and you have none entered",
        "Нужны результаты тестов, а у вас их нет",
        "Test natijalari talab qilinadi, sizda kiritilmagan",
    ),
    "profile.no_data": (
        "Not enough data about your fields or the acceptance rate",
        "Недостаточно данных о ваших направлениях и проценте приёма",
        "Yoʻnalishlar va qabul foizi haqida maʼlumot yetarli emas",
    ),
    "raise.profile.tests": (
        "Add a test score",
        "Добавьте результат теста",
        "Test natijasini qoʻshing",
    ),
    "raise.profile.fields": (
        "Pick your study fields",
        "Выберите направления обучения",
        "Oʻqish yoʻnalishlarini tanlang",
    ),
    "traits.city": (
        "Setting: {setting}",
        "Окружение: {setting}",
        "Joylashuv: {setting}",
    ),
    "traits.home": (
        "Distance from home: {distance}",
        "Расстояние от дома: {distance}",
        "Uydan masofa: {distance}",
    ),
    "traits.prestige": (
        "Selectivity: acceptance rate {rate}%",
        "Избирательность: процент приёма {rate}%",
        "Tanlov: qabul foizi {rate}%",
    ),
    "traits.social": (
        "International community: {share}% of students",
        "Международное сообщество: {share}% студентов",
        "Xalqaro hamjamiyat: talabalarning {share}%",
    ),
    "traits.no_data": (
        "No campus facts match what you said matters to you",
        "Нет данных о кампусе по тому, что для вас важно",
        "Siz uchun muhim narsalar boʻyicha kampus maʼlumoti yoʻq",
    ),
    "raise.traits.rate": (
        "Rate what matters to you",
        "Оцените, что для вас важно",
        "Siz uchun nima muhimligini baholang",
    ),
    "setting.urban": ("city", "город", "shahar"),
    "setting.suburban": ("suburb", "пригород", "shahar atrofi"),
    "setting.rural": ("countryside", "сельская местность", "qishloq"),
    "distance.same": ("in your country", "в вашей стране", "oʻz mamlakatingizda"),
    "distance.near": ("a nearby country", "соседняя страна", "qoʻshni mamlakat"),
    "distance.mid": (
        "a few hours by air",
        "несколько часов перелёта",
        "bir necha soatlik parvoz",
    ),
    "distance.far": ("far away", "далеко", "uzoqda"),
    "risk.low": ("low", "низкая", "past"),
    "risk.medium": ("medium", "средняя", "oʻrtacha"),
    "risk.high": ("high", "высокая", "yuqori"),
    "band.low": ("low", "низкий", "past"),
    "band.medium": ("medium", "средний", "oʻrtacha"),
    "band.high": ("high", "высокий", "yuqori"),
}


def msg(locale: str, key: str, **kwargs: object) -> str:
    """The line in the locale (unknown locale: English), formatted."""
    lines = _COPY[key]
    text = lines[LANGS.index(locale)] if locale in LANGS else lines[0]
    return text.format(**kwargs) if kwargs else text
