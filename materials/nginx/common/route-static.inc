# Static apps (sp, app, staff, admin, lms): served by the web container, which routes by Host.
location / {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_web;
}
