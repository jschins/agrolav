IF OBJECT_ID(N'dbo.map_condensed_balance', N'U') IS NULL
CREATE TABLE dbo.map_condensed_balance (
    id INT IDENTITY(1,1) PRIMARY KEY,
    country_id INT NOT NULL,
    post_name VARCHAR(64) NOT NULL,
    sum_local_code VARCHAR(256) NULL,
    section_name VARCHAR(64) NOT NULL,
    CONSTRAINT fk_map_condensed_country FOREIGN KEY (country_id) REFERENCES dbo.country (country_id)
);

-- Beheer condensed posts. country_id is looked up by username so the seed
-- still works if it is not 4. Does not overwrite an existing map.
INSERT INTO dbo.map_condensed_balance (country_id, post_name, sum_local_code, section_name)
SELECT c.country_id, v.post_name, v.sum_local_code, v.section_name
FROM dbo.country c
CROSS APPLY (VALUES
    (N'Gebouwen',             N'1000',                      N'Vaste activa'),
    (N'Verbouwingen',         N'1005',                      N'Vaste activa'),
    (N'Inventaris',           N'1010',                      N'Vaste activa'),
    (N'Auto''s',              N'1015',                      N'Vaste activa'),
    (N'Bank en Giro',         N'1051,1053,1054,1055,1056',  N'Vlottende activa'),
    (N'Kapitaalrekening',     N'1052',                      N'Vlottende activa'),
    (N'Debiteuren',           N'1110,1111',                 N'Vlottende activa'),
    (N'Eigen vermogen',       N'2000,2100',                 N'Passiva'),
    (N'Voorzieningen',        N'2050,2055',                 N'Passiva'),
    (N'Langlopende schulden', N'2500',                      N'Passiva'),
    (N'Kortlopende schulden', NULL,                         N'Passiva')
) v (post_name, sum_local_code, section_name)
WHERE c.username = N'beheer' COLLATE Latin1_General_CI_AI
  AND NOT EXISTS (
      SELECT 1 FROM dbo.map_condensed_balance m WHERE m.country_id = c.country_id
  );
