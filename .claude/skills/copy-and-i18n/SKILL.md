---
name: copy-and-i18n
description: Use when adding or changing any user-facing text in iht-backend - bot messages, notifications, mail, error messages, AI system prompts that set the answer language - covering uz/ru/en parity in locales/, the school terms ПК and ИК, and the Uzbek modifier letter apostrophe ʼ.
---

# Copy and i18n

## Parity

- Every key exists in `locales/uz`, `locales/ru` and `locales/en` with the same placeholders. Add all three in the same change; a missing key is a bug, not a fallback.
- Texts are looked up through `app/shared/i18n`; never hard-code a user-facing string in a handler.
- Errors carry a stable machine code; the message is translated.

## Terms

- "Промежуточный контроль (ПК)" and "Итоговый контроль (ИК)". **Never** "Рубежный контроль". Use the same terms in uz and en translations the school uses, consistently.
- "Урок" for a lesson; the school week is Monday to Friday.
- Product names: my.iht, IHT ID, IHT Учителям, admin.iht, lms.iht, library.iht.

## Uzbek

- Latin script. Use the modifier letter apostrophe **ʼ (U+02BC)** in `oʻ`/`gʻ` and the tutuq belgisi (`oʼquvchi`, `maʼlumot`), not `'` (U+0027) or `’` (U+2019). Search and matching normalise all three to `ʼ`.
- Check new strings with a grep for `'` and `’` inside `locales/uz`.

## Style

- Short, direct, polite "siz"/"вы"/"you". No exclamation marks in errors. Dates and times in Tashkent time, formatted per locale.
- Copy that mentions a limit or a deadline states the number.
