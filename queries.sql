-- #region Designs

-- :set MAX_DESIGNS = 120

-- :macro stale_designs()
-- params: pro, n
WITH slots_needed AS (
	SELECT {{ MAX_DESIGNS }} - (COUNT(designs) FILTER (WHERE pro = $1)) < $2
	FROM designs
)
SELECT design_id
FROM designs
WHERE
	pro = $1
	AND (SELECT * FROM slots_needed)
ORDER BY created_at
LIMIT $2
-- :endmacro

-- :macro delete_design()
-- params: design_id
DELETE FROM designs
WHERE design_id = $1
-- :endmacro

-- :macro delete_designs()
-- params: design_ids
DELETE FROM designs
WHERE design_id = ANY ($1)
-- :endmacro

-- :macro check_deletion_token()
-- params: image_id, deletion_token
SELECT deletion_token = $2
FROM images
WHERE image_id = $1
-- :endmacro

-- :macro delete_image_designs()
-- params: image_id
DELETE FROM designs
WHERE image_id = $1
RETURNING design_id
-- :endmacro

-- :macro delete_image()
-- params: image_id
DELETE FROM images
WHERE image_id = $1
-- :endmacro

-- :macro create_image()
-- params: author_name, image_name, width, height, layers, deletion_token
INSERT INTO images (author_name, image_name, width, height, type_code, layers, deletion_token)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING image_id
-- :endmacro

-- :macro create_design()
-- params: image_id, design_id, position, pro
INSERT INTO designs (image_id, design_id, position, pro)
VALUES ($1, $2, $3, $4)
RETURNING design_id
-- :endmacro

-- :macro image()
-- params: image_id
SELECT *
FROM images
WHERE image_id = $1
-- :endmacro

-- :macro image_designs()
-- params: image_id
SELECT *
FROM designs
WHERE image_id = $1
ORDER BY position
-- :endmacro

-- #endregion Designs

-- #region Authorization

-- :macro secret()
-- params: user_id
SELECT secret
FROM authorizations
WHERE user_id = $1
-- :endmacro

-- :macro authorize_user()
-- params: secret, description
INSERT INTO authorizations (secret, description)
VALUES ($1, $2)
RETURNING user_id
-- :endmacro

-- #endregion Authorization
