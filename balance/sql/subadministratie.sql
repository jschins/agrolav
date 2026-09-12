CREATE TABLE dbo.subadministratie (
    id INT IDENTITY(1,1) PRIMARY KEY,
    country_id INT NOT NULL,
    local_code INT NOT NULL,
    name VARCHAR(64) NOT NULL,
    amount DECIMAL(18,2) NOT NULL
);

ALTER TABLE dbo.subadministratie
ADD CONSTRAINT FK_subadministratie_dim_category
FOREIGN KEY (country_id, local_code)
REFERENCES dbo.dim_category (country_id, local_code);

INSERT INTO dbo.subadministratie VALUES
  (4, 2500, 'Driessen', 20606.20),
  (4, 2500, 'Ten Hage', 9333.32),
  (4, 2500, 'De Haro', 7361.39),
  (4, 2500, 'Schonebaum', 42902.63);