# mcp.<domain>: the three MCP servers (/student, /lms, /admin) and the OAuth
# protected-resource metadata. The api process serves them at the root of this host by
# Host routing (app/interfaces/http/routing.py install_mcp_host, from URLS__MCP), so the
# path goes through unchanged. Streamable HTTP needs buffering off and long timeouts.
location ~ ^/(student|lms|admin)(/|$) {
    include /etc/nginx/ihsp/proxy.inc;
    # The MCP apps are mounted with a trailing slash; Starlette would answer a bare
    # /student with a 307, which not every MCP client follows for a POST.
    rewrite ^/(student|lms|admin)$ /$1/ break;
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_pass $up_api;
}

location ^~ /.well-known/oauth-protected-resource/ {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_api;
}

location / {
    return 404;
}
