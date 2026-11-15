# Policy of the processes that read or store Telegram bot tokens (api, bot, worker).
path "secret/data/telegram-bots/*"     { capabilities = ["create", "read", "update"] }
path "secret/metadata/telegram-bots/*" { capabilities = ["read"] }
path "auth/token/renew-self"           { capabilities = ["update"] }
