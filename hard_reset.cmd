pause
pause
pause

del db.sqlite3
del games\migrations\0*.py
call m makemigrations games
call m migrate
call m initifdb
call m createsuperuser
