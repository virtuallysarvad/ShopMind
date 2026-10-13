<?php
// Creates a read/write WooCommerce REST API key for ShopMind (run via `wp eval-file`).
global $wpdb;
$table = $wpdb->prefix . 'woocommerce_api_keys';
$user  = get_user_by( 'login', 'admin' );
$wpdb->delete( $table, array( 'description' => 'ShopMind' ) );

$consumer_key    = 'ck_' . wc_rand_hash();
$consumer_secret = 'cs_' . wc_rand_hash();
$wpdb->insert( $table, array(
	'user_id'         => $user->ID,
	'description'     => 'ShopMind',
	'permissions'     => 'read_write',
	'consumer_key'    => wc_api_hash( $consumer_key ),
	'consumer_secret' => $consumer_secret,
	'truncated_key'   => substr( $consumer_key, -7 ),
) );

echo "SHOPMIND_WOO_MODE=live\n";
echo "SHOPMIND_WOO_STORE_URL=http://localhost:8080\n";
echo "SHOPMIND_WOO_CONSUMER_KEY={$consumer_key}\n";
echo "SHOPMIND_WOO_CONSUMER_SECRET={$consumer_secret}\n";
echo "SHOPMIND_WOO_WEBHOOK_SECRET=shopmind-local-webhook-secret\n";
