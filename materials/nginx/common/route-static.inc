# Static apps (sp, staff, admin, lms): served by the web container.
location / {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_web;
}
