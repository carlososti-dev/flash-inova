-- Executado na primeira subida do PostgreSQL do docker-compose.
-- A aplicacao usa um usuario SEM superusuario: so assim o Row Level Security vale para ela.
CREATE ROLE flash_app LOGIN PASSWORD 'flash_app' NOSUPERUSER NOBYPASSRLS;
