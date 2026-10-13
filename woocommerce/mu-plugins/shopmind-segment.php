<?php
/**
 * Plugin Name: ShopMind segment in wp-admin
 * Description: Shows the segment ShopMind writes back (customer meta "shopmind_segment") on the Users list, the user profile and the order screen, so approvals are visible in the store.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/** Badge HTML for a user's ShopMind segment, or a dash when none is set. */
function shopmind_segment_badge( $user_id ) {
	$segment = $user_id ? get_user_meta( (int) $user_id, 'shopmind_segment', true ) : '';
	if ( ! $segment ) {
		return '<span style="color:#999">&mdash;</span>';
	}
	$colors = array(
		'vip'     => '#b45309',
		'regular' => '#2563eb',
		'new'     => '#059669',
		'at_risk' => '#dc2626',
	);
	$color   = isset( $colors[ $segment ] ) ? $colors[ $segment ] : '#555';
	$label   = strtoupper( str_replace( '_', ' ', $segment ) );
	$updated = get_user_meta( (int) $user_id, 'shopmind_segment_updated', true );
	$title   = $updated ? 'Set by ShopMind on ' . $updated : 'Set by ShopMind';

	return sprintf(
		'<span title="%s" style="display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;color:#fff;background:%s">%s</span>',
		esc_attr( $title ),
		esc_attr( $color ),
		esc_html( $label )
	);
}

// Users list: a "ShopMind segment" column.
add_filter( 'manage_users_columns', function ( $columns ) {
	$columns['shopmind_segment'] = 'ShopMind segment';
	return $columns;
} );
add_filter( 'manage_users_custom_column', function ( $output, $column, $user_id ) {
	return 'shopmind_segment' === $column ? shopmind_segment_badge( $user_id ) : $output;
}, 10, 3 );

// User profile: read-only row.
$shopmind_profile_row = function ( $user ) {
	echo '<h2>ShopMind</h2><table class="form-table"><tr><th>Segment</th><td>'
		. shopmind_segment_badge( $user->ID ) // Escaped inside the helper.
		. '<p class="description">Written back by ShopMind when a segment change is approved.</p></td></tr></table>';
};
add_action( 'show_user_profile', $shopmind_profile_row );
add_action( 'edit_user_profile', $shopmind_profile_row );

// Order screen: under the billing address.
add_action( 'woocommerce_admin_order_data_after_billing_address', function ( $order ) {
	$user_id = $order ? $order->get_customer_id() : 0;
	if ( $user_id ) {
		echo '<p><strong>ShopMind segment:</strong> ' . shopmind_segment_badge( $user_id ) . '</p>';
	}
} );
