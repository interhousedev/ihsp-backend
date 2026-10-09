"""Words that carry no meaning in a question or a search (Russian, Uzbek, English)."""

RUSSIAN_STOP_WORDS = frozenset("""
    как что это для или его при про над под без они мне она был было были быть есть
    все всё вот там тут уже еще ещё если чем так тот эта этот эти этой этом того
    тому той кто где куда зачем почему когда какой какая какие каких каким какое
    чего чему нет нас вас них нам вам тоже также более очень можно нужно надо будет
    может могут между после перед через раз чтобы чтоб этого этих этим сколько
    расскажи объясни скажи покажи
    """.split())
UZBEK_STOP_WORDS = frozenset("""
    bilan uchun ham yoki lekin ammo ana mana ular biz siz men sen nima nega qanday
    qaysi qancha kim qayerda qachon uning bunga unda buni ushbu deb edi emas bor yoq
    kerak mumkin haqida menga bizga sizga aytib ayt tushuntir
    """.split())
ENGLISH_STOP_WORDS = frozenset("""
    the and for with what how why who when where which this that are was were from
    into about does did you your can will would should could have has had not but
    its their them they his her she him our out over than then also just only any
    all some such tell explain
    """.split())
STOP_WORDS = RUSSIAN_STOP_WORDS | UZBEK_STOP_WORDS | ENGLISH_STOP_WORDS
