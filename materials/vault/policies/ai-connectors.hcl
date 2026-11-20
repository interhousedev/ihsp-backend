# Policy of the processes that call model and search providers through the connectors
# added on the admin AI page (api, bot, worker, mcp): one secret per connector id.
path "secret/data/ai/connectors/*"     { capabilities = ["create", "read", "update"] }
path "secret/metadata/ai/connectors/*" { capabilities = ["read", "delete"] }
path "auth/token/renew-self"           { capabilities = ["update"] }
