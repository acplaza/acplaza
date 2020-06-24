-- #region Designs

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

-- :macro delete_image_designs()
-- params: image_id
DELETE FROM designs
WHERE image_id = $1
RETURNING design_id
-- :endmacro

-- :macro image_author_id()
-- params: image_id
SELECT author_id
FROM images
WHERE image_id = $1
-- :endmacro

-- :macro delete_image()
-- params: image_id
DELETE FROM images
WHERE image_id = $1
-- :endmacro

-- :macro create_image()
INSERT INTO images (author_id, author_name, image_name, width, height, mode, type_code, layers)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
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

-- :macro image_with_designs()
-- params: image_id
SELECT
	image_id,
	author_id,
	author_name,
	image_name,
	images.created_at,
	width,
	height,
	mode,
	layers,
	images.pro,
	type_code,
	design_id,
	position
FROM
	images
	LEFT JOIN designs USING (image_id)
WHERE image_id = $1
ORDER BY position
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
