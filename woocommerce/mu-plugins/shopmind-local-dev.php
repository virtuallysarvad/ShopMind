<?php
/**
 * Plugin Name: ShopMind local dev helpers
 * Description: Lets this local WooCommerce deliver webhooks to ShopMind on the host (http://host.docker.internal:8000). Local demos only.
 */

// WordPress blocks "unsafe" webhook targets: private IPs and ports other than 80/443/8080.
add_filter( 'http_request_host_is_external', '__return_true' );
add_filter( 'http_allowed_safe_ports', function ( $ports ) {
	$ports[] = 8000;
	return $ports;
} );

// Deliver webhooks immediately when an order is saved, instead of via wp-cron
// (wp-cron's loopback request cannot reach localhost:8080 from inside Docker).
add_filter( 'woocommerce_webhook_deliver_async', '__return_false' );
