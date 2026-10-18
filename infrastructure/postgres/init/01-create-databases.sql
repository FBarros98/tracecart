-- Executed once by the official postgres image, only when the data volume is empty.
-- Creates one database and one dedicated role per microservice. Credentials come from the
-- container environment (psql \getenv), so no secret is stored in this file.
--
-- Isolation: each role owns only its database and CONNECT is revoked from PUBLIC, so the
-- Order Service cannot connect to tracecart_payments and vice versa.

\set ON_ERROR_STOP on

\getenv order_db_user ORDER_DB_USER
\getenv order_db_password ORDER_DB_PASSWORD
\getenv payment_db_user PAYMENT_DB_USER
\getenv payment_db_password PAYMENT_DB_PASSWORD

CREATE ROLE :"order_db_user" WITH LOGIN PASSWORD :'order_db_password';
CREATE ROLE :"payment_db_user" WITH LOGIN PASSWORD :'payment_db_password';

CREATE DATABASE tracecart_orders OWNER :"order_db_user";
CREATE DATABASE tracecart_payments OWNER :"payment_db_user";

REVOKE ALL ON DATABASE tracecart_orders FROM PUBLIC;
REVOKE ALL ON DATABASE tracecart_payments FROM PUBLIC;
