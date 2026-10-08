# Common proxy settings (timeouts are set once in default.conf.template; the MCP route
# overrides them). X-Forwarded-For is overwritten with the real client address, never
# appended: the backend trusts it only from this container (uvicorn FORWARDED_ALLOW_IPS).
proxy_http_version 1.1;
proxy_set_header Host              $http_host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host  $http_host;
proxy_set_header Connection        "";
