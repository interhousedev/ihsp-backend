# Static apps (sp, app, staff, admin, lms): served by the web container, which routes by Host.
location / {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_web;
# The web container sends relative redirects (absolute_redirect off); rewrite any absolute one
# that still names its internal port 8080 to the public https host.
proxy_redirect ~^http://[^/]+:8080/(.*)$ https://$host/$1;
}
