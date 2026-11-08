@echo off
echo ================================================
echo  重置智碳管家数据库
echo ================================================
echo.

set DB_PATH=D:\Carbon_AI_Project\carbon_ai\carbon_ai.db
set DB_PATH_2=D:\Carbon_AI_Project\carbon_ai.db

if exist "%DB_PATH%" (
    echo 正在删除数据库: %DB_PATH%
    del "%DB_PATH%"
    echo 数据库已删除
) else (
    echo 数据库文件不存在: %DB_PATH%
)

if exist "%DB_PATH_2%" (
    echo 正在删除数据库: %DB_PATH_2%
    del "%DB_PATH_2%"
    echo 数据库已删除
)

if exist "D:\Carbon_AI_Project\data\chroma_db\chroma.sqlite3" (
    echo 正在删除向量库: chroma.sqlite3
    del "D:\Carbon_AI_Project\data\chroma_db\chroma.sqlite3"
    echo 向量库已删除
)

echo.
echo ================================================
echo  数据库已重置！
echo  下次启动后端时会自动重新创建
echo ================================================
echo.
pause
