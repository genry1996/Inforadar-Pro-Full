# CLEANUP SCRIPT - Удаляем старые файлы

# Удаляем ВСЕ старые версии betwatch парсеров (оставляем только главный)
del D:\Inforadar_Pro\inforadar_parser\betwatch_debug_v2.py
del D:\Inforadar_Pro\inforadar_parser\betwatch_debug_v3.py
del D:\Inforadar_Pro\inforadar_parser\betwatch_debug.py
del D:\Inforadar_Pro\inforadar_parser\betwatch_debug.html
del D:\Inforadar_Pro\inforadar_parser\betwatch_debug.png
del D:\Inforadar_Pro\inforadar_parser\betwatch_improved.py
del D:\Inforadar_Pro\inforadar_parser\betwatch_parser_api_fixed.py
del D:\Inforadar_Pro\inforadar_parser\betwatch_parser_final.py
del D:\Inforadar_Pro\inforadar_parser\betwatch_parser_OLD.py
del D:\Inforadar_Pro\inforadar_parser\betwatch_parser_production.py
del D:\Inforadar_Pro\inforadar_parser\betwatch_parser_v5_fixed.py

# Удаляем дублирующие файлы 22bet
del D:\Inforadar_Pro\inforadar_parser\parser_22bet.py
del D:\Inforadar_Pro\inforadar_parser\detector_22bet.py
del D:\Inforadar_Pro\inforadar_parser\check_22bet_mirrors.py

# Удаляем старые конфиги и тесты
del D:\Inforadar_Pro\inforadar_parser\config_22bet.py
del D:\Inforadar_Pro\inforadar_parser\test_pinnacle.py
del D:\Inforadar_Pro\inforadar_parser\proxy_test_playwright_socks.py
del D:\Inforadar_Pro\inforadar_parser\proxy_test_playwright.py
del D:\Inforadar_Pro\inforadar_parser\proxy_test.py
del D:\Inforadar_Pro\inforadar_parser\proxy_verify.py
del D:\Inforadar_Pro\inforadar_parser\dump_html.py

# Удаляем большие HTML файлы (они займут место)
del D:\Inforadar_Pro\inforadar_parser\debug_22bet_basketball.html
del D:\Inforadar_Pro\inforadar_parser\debug_22bet_football.html

echo ✅ Очистка завершена!
echo Осталось:
dir D:\Inforadar_Pro\inforadar_parser\*.py
