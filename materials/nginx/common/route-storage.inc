# storage.<domain> (optional, only with the `rustfs` compose profile): presigned PUT/GET
# requests go straight to the bundled RustFS. The Host header must reach it unchanged,
# because the S3 signature covers it (docs/reference/jobs-storage-vault.md § 2.4).
location / {
    include /etc/nginx/ihsp/proxy.inc;
    client_max_body_size 128m;
    proxy_request_buffering off;
    proxy_buffering off;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;
    proxy_pass $up_s3;
}
