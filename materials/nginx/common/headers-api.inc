# Response headers of the JSON endpoints (api., mcp.): nothing is a document, so nothing may
# be framed, embedded or rendered. Included in every location that proxies to a backend
# process: an add_header in a location replaces the server's add_header list, which is why
# HSTS (tls.inc.template) is repeated here (a browser ignores it over plain HTTP).
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer" always;
add_header Content-Security-Policy "default-src 'none'; frame-ancestors 'none'" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
