"""Per-institution profile and demo media of the seed catalog.

Media are Wikimedia Commons files (``upload.wikimedia.org``), each checked for an
image response; a university without a verified file has no entry for it.
"""

from __future__ import annotations

from typing import Final

# slug -> city_type, institution_type, logo_url, cover_url
PROFILES: Final[dict[str, dict[str, str]]] = {
    "harvard": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/7/70/Harvard_University_logo.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/1/11/Sanders_theater_2009y.JPG/960px-Sanders_theater_2009y.JPG"
        ),
    },
    "mit": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/b/b8/MIT_2023_red_logo.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/MIT_Dome_night1_Edit.jpg/960px-MIT_Dome_night1_Edit.jpg"
        ),
    },
    "stanford": {
        "city_type": ("suburban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/a/a9/Stanford_wordmark_%282012%29.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cd/Stanford_Oval_May_2011_panorama.jpg/960px-Stanford_Oval_May_2011_panorama.jpg"
        ),
    },
    "yale": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/0/07/Yale_University_Shield_1.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fb/Yale_Law_School_in_the_Sterling_Law_Building.jpg/960px-Yale_Law_School_in_the_Sterling_Law_Building.jpg"
        ),
    },
    "princeton": {
        "city_type": ("suburban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/4/42/Princeton_text_logo.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d1/ClevelandTowerWatercolor20060829.jpg/960px-ClevelandTowerWatercolor20060829.jpg"
        ),
    },
    "columbia": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/a/a6/Columbia_University_Shield.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0e/Columbia_University_-_Low_Memorial_Library_%2848170370506%29.jpg/960px-Columbia_University_-_Low_Memorial_Library_%2848170370506%29.jpg"
        ),
    },
    "upenn": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/9/92/UPenn_shield_with_banner.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/d/df/College_Hall%2C_University_of_Pennsylvania.jpg/960px-College_Hall%2C_University_of_Pennsylvania.jpg"
        ),
    },
    "cornell": {
        "city_type": ("rural"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/4/47/Cornell_University_seal.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/3/34/Cornell_University%2C_Ho_Plaza_and_Sage_Hall.jpg/960px-Cornell_University%2C_Ho_Plaza_and_Sage_Hall.jpg"
        ),
    },
    "duke": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/e/e6/Duke_University_logo.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/af/Duke_Chapel_4_16_05.jpg/960px-Duke_Chapel_4_16_05.jpg"
        ),
    },
    "jhu": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/5/51/Johns_Hopkins_University_logo.png"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/70/Johns_Hopkins%27_Historic_Dome_-_panoramio.jpg/960px-Johns_Hopkins%27_Historic_Dome_-_panoramio.jpg"
        ),
    },
    "nyu": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/6/6a/Nyu_short_color.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/NYU07.JPG/960px-NYU07.JPG"
        ),
    },
    "cmu": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/f/f3/Carnegie_Mellon_University_wordmark.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/8/85/CMU_campus_Cathedral_Learning_background.jpg/960px-CMU_campus_Cathedral_Learning_background.jpg"
        ),
    },
    "gatech": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/6/6c/Georgia_Tech_seal.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/Georgiatechsign2.jpg/960px-Georgiatechsign2.jpg"
        ),
    },
    "umich": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/c/c1/University_of_Michigan_logo.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/6/63/AngellHall2010.JPG/960px-AngellHall2010.JPG"
        ),
    },
    "oxford": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/2/2f/University_of_Oxford.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b8/1_oxford_aerial_panorama_2016.jpg/960px-1_oxford_aerial_panorama_2016.jpg"
        ),
    },
    "imperial": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/0/06/Imperial_College_London_new_logo.png"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9d/Imperial_College_London_down_Exhibition_Road.jpg/960px-Imperial_College_London_down_Exhibition_Road.jpg"
        ),
    },
    "cambridge": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/4/4d/University_of_Cambridge_logo.png"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/4/41/St_John%27s_College_Second_Court%2C_Cambridge%2C_UK_-_Diliff.jpg/960px-St_John%27s_College_Second_Court%2C_Cambridge%2C_UK_-_Diliff.jpg"
        ),
    },
    "ucl": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/0/0f/UCL_Crest.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/0/03/Wilkins_Building_1%2C_UCL%2C_London_-_Diliff.jpg/960px-Wilkins_Building_1%2C_UCL%2C_London_-_Diliff.jpg"
        ),
    },
    "tum": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/4/4c/TU_Muenchen_Logo.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/2/28/Technische_Universitaet_Muenchen-1.jpg/960px-Technische_Universitaet_Muenchen-1.jpg"
        ),
    },
    "heidelberg": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/4/4f/Logo_University_of_Heidelberg.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/3/30/Friedrichsbau_Heidelberg_Altstadt_Bunsen_Statue.JPG/960px-Friedrichsbau_Heidelberg_Altstadt_Bunsen_Statue.JPG"
        ),
    },
    "bocconi": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/4/4c/Bocconi_University_Logo.svg"
        ),
    },
    "polimi": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/5/5b/Politecnicomilano-logo.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/Polimi_Leonardo_campus_main_building.jpg/960px-Polimi_Leonardo_campus_main_building.jpg"
        ),
    },
    "bologna": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/d/d0/Seal_of_the_University_of_Bologna.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/73/C%C3%A0_Grande_dei_Malvezzi_-_Sala_Borsa_06.jpg/960px-C%C3%A0_Grande_dei_Malvezzi_-_Sala_Borsa_06.jpg"
        ),
    },
    "corvinus": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/5/57/Corvinus_eng_logo.jpg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/c/ce/Corvinus_foepulet.jpg/960px-Corvinus_foepulet.jpg"
        ),
    },
    "semmelweis": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/0/07/Logo_univsemmelweis.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Semmelweis_University%2C_main_building.jpg/960px-Semmelweis_University%2C_main_building.jpg"
        ),
    },
    "elte": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/8/80/ELTE_logo_new.svg"
        ),
    },
    "kaist": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/0/0a/KAIST_logo.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7f/KAIST-Symbol-01.jpg/960px-KAIST-Symbol-01.jpg"
        ),
    },
    "snu": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/9/9e/Seoul_national_university_logotype.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3d/SeoulNatlUnivMainGateAtNight.jpg/960px-SeoulNatlUnivMainGateAtNight.jpg"
        ),
    },
    "yonsei": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/6/6e/Yonsei_University_logotype%28ko%29.png"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/Yeonsei_university_2011_%2816%29.JPG/960px-Yeonsei_university_2011_%2816%29.JPG"
        ),
    },
    "utokyo": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/d/d6/University_of_Tokyo_logo_%282024%29.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/Yasuda_Auditorium_-_Tokyo_University_3.jpg/960px-Yasuda_Auditorium_-_Tokyo_University_3.jpg"
        ),
    },
    "waseda": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": ("https://upload.wikimedia.org/wikipedia/commons/f/f2/Waseda.png"),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/Okuma_Auditorium.jpg/960px-Okuma_Auditorium.jpg"
        ),
    },
    "bilkent": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/b/b4/Bilkentlogo.png"
        ),
    },
    "koc": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/2/24/Ko%C3%A7_University_logo.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/b/ba/Ko%C3%A7University2.jpg/960px-Ko%C3%A7University2.jpg"
        ),
    },
    "metu": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/a/ab/Logo_ODT%C3%9C.svg"
        ),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/MiddleEastTechnicalUniversityCampus800x470.jpg/960px-MiddleEastTechnicalUniversityCampus800x470.jpg"
        ),
    },
    "monash-malaysia": {
        "city_type": ("suburban"),
        "institution_type": ("private"),
        "cover_url": (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/9/93/Cmglee_Sunway_Monash_University.jpg/960px-Cmglee_Sunway_Monash_University.jpg"
        ),
    },
    "taylors": {
        "city_type": ("suburban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/6/69/Logo-Taylors-University.png"
        ),
    },
    "nyuad": {
        "city_type": ("urban"),
        "institution_type": ("private"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/3/35/NYU_Abu_Dhabi_Logo%28cropped%29.jpg"
        ),
    },
    "khalifa": {
        "city_type": ("urban"),
        "institution_type": ("public"),
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/c/c5/Khalifa_University_New_Logo.png"
        ),
    },
}
