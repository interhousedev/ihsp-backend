# HashiCorp Vault 2.1 server config for production: one node, integrated (Raft) storage.
# docs/reference/jobs-storage-vault.md § 3.5.
#
# The listener is plain HTTP on purpose: port 8200 is never published; only containers
# on the internal Docker network (identity, vault init and backup jobs) can reach it.
# Vault starts sealed after every restart: unseal it with `scripts/prod_init.sh unseal`.

# Required to be explicit with Raft storage (Vault refuses to start otherwise). Raft
# recommends `true` because its storage is memory-mapped and must not be locked.
disable_mlock = true

ui = false
log_level = "info"

storage "raft" {
  path    = "/vault/file"
  node_id = "ihsp-vault-1"
}

listener "tcp" {
  address         = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_disable     = true
}

api_addr     = "http://vault:8200"
cluster_addr = "http://vault:8201"
