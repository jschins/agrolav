ALTER TABLE dbo.country ADD digits CONSTRAINT DF_number_digits DEFAULT 2;
set 4 @ beheer
DELETE FROM dbo.category_term WHERE category_id >=400;

ALTER TABLE dbo.transaction_beheer DROP CONSTRAINT ck_txn_beheer_cat;

UPDATE dbo.dim_category SET category_id = 13997 WHERE category_id = 401;

UPDATE dbo.transaction_beheer SET category_id = 13997 WHERE category_id = 402;

UPDATE dbo.dim_category SET category_id = 13999 WHERE category_id = 402;

UPDATE dbo.transaction_beheer SET category_id = 13999 WHERE category_id = 13997;

ALTER TABLE dbo.transaction_beheer ADD CONSTRAINT ck_txn_beheer_cat CHECK ([category_id] >= 13000 AND [category_id] <= 13999);