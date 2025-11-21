@echo off
set LOG_FILE=auto.log
echo Logging started at %DATE% %TIME% >> %LOG_FILE%
echo ================================================= >> %LOG_FILE%
echo.
call :LOG >> %LOG_FILE%
exit /B

:LOG
C:\Windows\py.exe C:\Users\thinhnguyen_blog1\Downloads\PortableGit\autopost\create_ad_post.py %*