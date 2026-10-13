#!/usr/bin/env bash
# One-time setup of the local ShopMind demo store. Safe to re-run.
# Start the ShopMind backend (port 8000) first so WooCommerce's webhook ping succeeds.
set -euo pipefail
cd /var/www/html

echo "==> Waiting for WordPress files and the database"
for i in $(seq 1 60); do
  [ -f wp-config.php ] && php -r 'exit(@mysqli_connect("db","wordpress","wordpress","wordpress") ? 0 : 1);' && break
  sleep 2
done

if ! wp core is-installed 2>/dev/null; then
  echo "==> Installing WordPress"
  wp core install --url=http://localhost:8080 --title="ShopMind Demo Store" \
    --admin_user=admin --admin_password=admin --admin_email=admin@example.com --skip-email
fi

echo "==> Updating WordPress (current WooCommerce needs WordPress 7.0+)"
wp core update
wp core update-db

echo "==> Pretty permalinks (needed for /wp-json/)"
wp rewrite structure '/%postname%/'
cat > .htaccess <<'HT'
# BEGIN WordPress
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
RewriteBase /
RewriteRule ^index\.php$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . /index.php [L]
</IfModule>
# END WordPress
HT

echo "==> Installing WooCommerce"
wp plugin is-installed woocommerce || wp plugin install woocommerce
wp plugin activate woocommerce

echo "==> Store settings: India, rupees"
wp option update woocommerce_currency INR
wp option update woocommerce_default_country "IN:GA"
wp option update woocommerce_store_address "Station Road"
wp option update woocommerce_store_city "Margao"
wp option update woocommerce_store_postcode "403601"
wp option update woocommerce_coming_soon "no" || true
wp option update woocommerce_onboarding_profile '{"skipped":true}' --format=json || true

if [ "$(wp wc product list --user=admin --format=count)" = "0" ]; then
  echo "==> Products"
  declare -A P
  P[earbuds]=$(wp wc product create --user=admin --name="Wireless Earbuds" --regular_price=2499 --porcelain)
  P[tea]=$(wp wc product create --user=admin --name="Assam Green Tea (50 bags)" --regular_price=399 --porcelain)
  P[stand]=$(wp wc product create --user=admin --name="Aluminium Laptop Stand" --regular_price=1299 --porcelain)
  P[shoes]=$(wp wc product create --user=admin --name="Running Shoes Pro" --regular_price=3999 --porcelain)
  P[mugs]=$(wp wc product create --user=admin --name="Ceramic Mug Set (4)" --regular_price=899 --porcelain)
  P[bottle]=$(wp wc product create --user=admin --name="Steel Water Bottle" --regular_price=599 --porcelain)

  billing() { # first last email phone
    printf '{"first_name":"%s","last_name":"%s","email":"%s","phone":"%s","city":"Margao","state":"GA","country":"IN","postcode":"403601","address_1":"Station Road"}' "$1" "$2" "$3" "$4"
  }
  customer() { # first last email phone -> id
    wp wc customer create --user=admin --email="$3" --first_name="$1" --last_name="$2" \
      --billing="$(billing "$1" "$2" "$3" "$4")" --porcelain
  }
  order() { # customer_id billing_json status product qty
    wp wc shop_order create --user=admin --customer_id="$1" --billing="$2" --status="$3" \
      --set_paid=$([ "$3" = completed ] && echo true || echo false) \
      --line_items="[{\"product_id\":$4,\"quantity\":$5}]" --porcelain >/dev/null
  }

  echo "==> Customers and orders"
  PRIYA=$(customer Priya Kamat priya@example.com 9822000001)
  ROHAN=$(customer Rohan Naik rohan@example.com 9822000002)
  SNEHA=$(customer Sneha Desai sneha@example.com 9822000003)
  B_PRIYA=$(billing Priya Kamat priya@example.com 9822000001)
  B_ROHAN=$(billing Rohan Naik rohan@example.com 9822000002)
  B_SNEHA=$(billing Sneha Desai sneha@example.com 9822000003)
  B_GUEST=$(billing Arjun Shetty arjun@example.com 9822000004)

  # Priya: loyal big spender -> VIP candidate
  for p in shoes earbuds shoes stand earbuds shoes; do order "$PRIYA" "$B_PRIYA" completed "${P[$p]}" 1; done
  # Rohan: a failed payment -> issue alert
  order "$ROHAN" "$B_ROHAN" completed "${P[tea]}" 2
  order "$ROHAN" "$B_ROHAN" failed "${P[earbuds]}" 1
  # Sneha: two refunds -> repeated returns
  order "$SNEHA" "$B_SNEHA" refunded "${P[mugs]}" 1
  order "$SNEHA" "$B_SNEHA" refunded "${P[bottle]}" 2
  order "$SNEHA" "$B_SNEHA" processing "${P[stand]}" 1
  # Arjun: guest checkout
  order 0 "$B_GUEST" processing "${P[bottle]}" 1
fi

echo "==> Webhooks to ShopMind (http://host.docker.internal:8000)"
for id in $(wp wc webhook list --user=admin --field=id 2>/dev/null); do
  wp wc webhook delete "$id" --user=admin --force=true >/dev/null
done
for topic in order.created order.updated; do
  wp wc webhook create --user=admin --name="ShopMind $topic" --topic="$topic" --status=active \
    --delivery_url="http://host.docker.internal:8000/webhooks/woocommerce/order" \
    --secret="shopmind-local-webhook-secret" --porcelain >/dev/null \
    || echo "  ! Could not create the $topic webhook. Start the ShopMind backend on port 8000 and re-run this script."
done

echo "==> REST API key for ShopMind"
wp eval-file /scripts/create-api-key.php | tee /scripts/shopmind-woo.env

cat <<'DONE'

All set. Store: http://localhost:8080  (admin / admin at /wp-admin)
Copy the lines above into backend/.env (also saved to woocommerce/scripts/shopmind-woo.env),
start the ShopMind backend, then press "Sync now" on the dashboard.
DONE
