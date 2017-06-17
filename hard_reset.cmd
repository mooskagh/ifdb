pause
pause
pause

del db.sqlite3
rem del games\migrations\0*.py
call m makemigrations games
call m migrate
call m initifdb
call m createsuperuser
