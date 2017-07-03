exit
rmdir /s games\static\urqw
pause
mkdir games\static\urqw
xcopy ..\urqw\js\* games\static\urqw /E
xcopy ..\urqw\lang games\static\urqw\lang /E /I
xcopy ..\urqw\vendor\bootstrap\fonts games\static\urqw\fonts /E /I
copy ..\urqw\css\* games\static\urqw
copy ..\urqw\logo.svg games\static\urqw
mkdir games\static\urqw\vendor
copy ..\urqw\vendor\bootstrap\dist\js\bootstrap.min.js games\static\urqw\vendor
copy ..\urqw\vendor\bootstrap\dist\css\bootstrap.min.css games\static\urqw\vendor
copy ..\urqw\vendor\jszip\dist\jszip.min.js games\static\urqw\vendor
copy ..\urqw\vendor\jszip-utils\dist\jszip-utils.min.js games\static\urqw\vendor

