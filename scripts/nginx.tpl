{% for c in configs %}
{% if c.conf == 'prod' %}
upstream django {
    server unix:///home/ifdb/configs/uwsgi.socket;
}
{% elif c.conf == 'staging' %}
upstream django-staging {
    server unix:///home/ifdb/configs/uwsgi-staging.socket;
}
{% elif c.conf == 'kontigr' %}
upstream django-kontigr {
    server unix:///home/ifdb/configs/uwsgi-kontigr.socket;
}
{% elif c.conf == 'zok' %}
upstream django-zok {
    server unix:///home/ifdb/configs/uwsgi-zok.socket;
}
{% endif %}
server {
{% if c.host == 'prod' %}
    server_name db.crem.xyz;

    error_log    /home/ifdb/logs/nginx-error.log;
    access_log    /home/ifdb/logs/nginx-access.log main;

    listen 443 ssl;
    listen [::]:443 ssl;
    ssl_certificate /etc/letsencrypt/live/db.crem.xyz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/db.crem.xyz/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    if ($scheme != "https") {
        return 301 https://$host$request_uri;
    } # managed by Certbot
{% elif c.host == 'kontigr' %}
    server_name kontigr.com;

    error_log    /home/ifdb/logs/nginx-kontigr-error.log;
    access_log    /home/ifdb/logs/nginx-kontigr-access.log main;

    listen 443 ssl;
    listen [::]:443 ssl;
    ssl_certificate /etc/letsencrypt/live/kontigr.com/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/kontigr.com/privkey.pem; # managed by Certbot    
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    if ($scheme != "https") {
       return 301 https://$host$request_uri;
    } # managed by Certbot

{% elif c.host == 'zok' %}
    server_name zok.quest;

    error_log    /home/ifdb/logs/nginx-zok-error.log;
    access_log    /home/ifdb/logs/nginx-zok-access.log main;


    listen [::]:443 ssl ipv6only=on; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/zok.quest/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/zok.quest/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot

    if ($scheme != "https") {
       return 301 https://$host$request_uri;
    } # managed by Certbot

{% elif c.host == 'staging' %}
    server_name db-staging.crem.xyz;

    error_log    /home/ifdb/logs/nginx-staging-error.log;
    access_log    /home/ifdb/logs/nginx-staging-access.log;

    auth_basic "This place is closed.";
    auth_basic_user_file /home/ifdb/configs/htpasswd;
{% endif %}

    listen 80;
    listen       [::]:80;

    charset     utf-8;

    client_max_body_size 512M;

{% if c.conf == 'prod' %}
    rewrite ^/$ /index/ last;

    location /f/  {
        alias /home/ifdb/files/;
    }

    location /static/ {
        alias /home/ifdb/static/;
    }

    location / {
        uwsgi_pass  django;
        include     /home/ifdb/configs/uwsgi_params;
    }

{% elif c.conf == 'kontigr' %}
    location /f/  {
        alias /home/ifdb/files/;
    }

    location /static/ {
        alias /home/ifdb/static/;
    }

    location / {
        uwsgi_pass  django-kontigr;
        include     /home/ifdb/configs/uwsgi_params;
    }

{% elif c.conf == 'zok' %}
    location /f/  {
        alias /home/ifdb/files/;
    }

    location /static/ {
        alias /home/ifdb/static/;
    }

    location / {
        uwsgi_pass  django-zok;
        include     /home/ifdb/configs/uwsgi_params;
    }

{% elif c.conf == 'staging' %}
    location /f/  {
        alias /home/ifdb/files/;
    }

    location /static/ {
        alias /home/ifdb/staging/static/;
    }

    location / {
        uwsgi_pass  django-staging;
        include     /home/ifdb/configs/uwsgi_params;
    }
{% elif c.conf == 'deny' %}
    location / {
        deny all;
        return 403;
    }
{% elif c.conf == 'wallpage' %}
    location / {
        root /home/ifdb/configs/wallpage;
        try_files $uri /index.html;
    }
{% endif %}
}
{% endfor %}
