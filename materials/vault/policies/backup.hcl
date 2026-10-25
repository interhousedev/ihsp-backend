# Policy of the backup job (scripts/backup.sh): take Raft snapshots, nothing else.
path "sys/storage/raft/snapshot" { capabilities = ["read"] }
path "auth/token/renew-self"     { capabilities = ["update"] }
