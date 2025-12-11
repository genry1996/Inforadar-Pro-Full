# Скрипт для создания пользователя в MySQL

docker exec mysql_inforadar mysql -uroot -pryban8991! -e "
CREATE USER IF NOT EXISTS 'inforadar_user'@'%' IDENTIFIED BY 'inforadar_password';
GRANT ALL PRIVILEGES ON inforadar.* TO 'inforadar_user'@'%';
FLUSH PRIVILEGES;
"

echo "✅ Пользователь inforadar_user создан!"
