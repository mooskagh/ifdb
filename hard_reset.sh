#!/bin/bash

read -n1 -r -p "Press any key to continue..." key
read -n1 -r -p "Press any key to continue..." key
read -n1 -r -p "Press any key to continue..." key

cat drop_all.sql | ./manage.py dbshell
rm -fr files/backups/* del files/recodes/* del files/uploads/*

# rem git diff --name-only release | perl -pe "s#/#\\#g;" | for /f "delims=" %%a in ('findstr migrations\0') do del "%%a"
./manage.py makemigrations games
./manage.py makemigrations core

read -n1 -r -p "Press any key to continue..." key
./manage.py migrate
./manage.py initifdb
./manage.py createsuperuser --email "ersatzplut+bot@gmail.com" --username "бездушный робот" --noinput
./manage.py createsuperuser --email "mooskagh@gmail.com" --username "crem"
