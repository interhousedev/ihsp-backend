# Policy of the identity process (docs/reference/jobs-storage-vault.md § 3.4).
path "secret/data/emis/*"             { capabilities = ["create", "read", "update"] }
path "secret/metadata/emis/*"         { capabilities = ["read", "delete"] }
path "transit/encrypt/emis-passwords" { capabilities = ["update"] }
path "transit/decrypt/emis-passwords" { capabilities = ["update"] }
path "auth/token/renew-self"          { capabilities = ["update"] }
