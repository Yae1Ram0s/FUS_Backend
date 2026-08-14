# PyMySQL se hace pasar por MySQLdb (el driver que Django espera para
# django.db.backends.mysql) — así no hace falta mysqlclient, que requiere
# compilar una extensión C contra las librerías de MySQL instaladas en el
# sistema. Tiene que ejecutarse antes de que cualquier otra cosa importe
# MySQLdb, así que va en el __init__.py del paquete del proyecto (lo primero
# que Django carga al arrancar).
import pymysql

pymysql.install_as_MySQLdb()
