# Policy of the identity process.
path "secret/data/emis/*"             { capabilities = ["create", "read", "update"] }
path "secret/metadata/emis/*"         { capabilities = ["read", "delete"] }
path "transit/encrypt/emis-passwords" { capabilities = ["update"] }
path "transit/decrypt/emis-passwords" { capabilities = ["update"] }
path "auth/token/renew-self"          { capabilities = ["update"] }
