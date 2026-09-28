-- Runs once, when the postgres volume is first initialized.
-- Separate database for the test suite (tests refuse to run against a non-*_test DB).
CREATE DATABASE lingo_test;
