@echo off
REM ===========================================================================
REM  NER Spatial Coverage Analyzer - setup WITHOUT administrator rights
REM
REM  Double-click this file on a computer where administrator rights cannot
REM  be granted (a managed laptop). It runs setup.bat with --no-admin: the
REM  application is installed for this account only, in your own profile
REM  (%LOCALAPPDATA%\Programs\ner-analyzer), with its sign-in task and
REM  watchdog registered for this account, and nothing written outside it.
REM  Everything else - the backup of a previous installation, the clean-up of
REM  the installation files - is exactly as with setup.bat.
REM
REM  (c) 2026 Marcelo Barbosa. Free software, GNU AGPL-3.0 - see LICENSE.txt and NOTICE.txt.
REM ===========================================================================
call "%~dp0setup.bat" --no-admin %*
