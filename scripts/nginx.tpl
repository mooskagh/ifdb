{% for c in configs %}
{% if c.conf == 'prod' %}
upstream django {
    server unix:///home/ifdb/configs/uwsgi.socket;
}
{% elif c.conf == 'staging' %}
upstream django-staging {
    server unix:///home/ifdb/configs/uwsgi-staging.socket;
}
{% endif %}
server {
{% if c.host == 'prod' %}
    server_name db.mooskagh.com;

    error_log    /home/ifdb/logs/nginx-error.log;
    access_log    /home/ifdb/logs/nginx-access.log;
{% elif c.host == 'staging' %}
    server_name db-staging.mooskagh.com;

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
    location /uploads  {
        alias /home/ifdb/uploads;
    }

    location /static {
        alias /home/ifdb/static;
    }

    location / {
        uwsgi_pass  django;
        include     /home/ifdb/configs/uwsgi_params;
    }
{% elif c.conf == 'staging' %}
    location /uploads  {
        alias /home/ifdb/uploads;
    }

    location /static {
        alias /home/ifdb/static;
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
