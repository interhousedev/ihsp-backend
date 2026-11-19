# Policy of the processes that seal and open essay text (api, bot, worker, mcp): one
# data key per student; erasure deletes the key with all its versions (crypto-shredding).
path "secret/data/admission-essays/*"     { capabilities = ["create", "read", "update"] }
path "secret/metadata/admission-essays/*" { capabilities = ["read", "delete"] }
path "auth/token/renew-self"              { capabilities = ["update"] }
