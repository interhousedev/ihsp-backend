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
# OAuth redirects carry Hydra challenges of several KB (ChatGPT sends long requests):
# the default 4k header buffer answers them with 502 "upstream sent too big header".
proxy_buffer_size 32k;
proxy_buffers     8 32k;
proxy_busy_buffers_size 64k;
