<?php
/**
 * [mep_calendario] – calendario eventi con viste giorno / settimana / mese / prossimi,
 * ricerca e filtri per provincia e comune (dal luogo dell'evento).
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

add_shortcode( 'mep_calendario', 'mep_cal_shortcode' );

const MEP_CAL_PROV = array(
	'BG' => 'Bergamo',
	'BS' => 'Brescia',
	'SO' => 'Sondrio',
);

function mep_cal_param( $k, $default = '' ) {
	// phpcs:ignore WordPress.Security.NonceVerification.Recommended -- filtri pubblici in sola lettura
	return isset( $_GET[ $k ] ) ? sanitize_text_field( wp_unslash( $_GET[ $k ] ) ) : $default;
}

/** Elenco comuni (con provincia) dai luoghi degli eventi, in cache 6 ore. */
function mep_cal_places() {
	$places = get_transient( 'mep_cal_places' );
	if ( false !== $places ) {
		return $places;
	}
	global $wpdb;
	// phpcs:ignore WordPress.DB.DirectDatabaseQuery
	$rows = $wpdb->get_results(
		"SELECT DISTINCT c.meta_value AS city, COALESCE(NULLIF(pr.meta_value,''), NULLIF(sp.meta_value,'')) AS prov
		 FROM {$wpdb->posts} p
		 JOIN {$wpdb->postmeta} c ON c.post_id = p.ID AND c.meta_key = '_VenueCity'
		 LEFT JOIN {$wpdb->postmeta} pr ON pr.post_id = p.ID AND pr.meta_key = '_VenueProvince'
		 LEFT JOIN {$wpdb->postmeta} sp ON sp.post_id = p.ID AND sp.meta_key = '_VenueStateProvince'
		 WHERE p.post_type = 'tribe_venue' AND p.post_status = 'publish' AND c.meta_value <> ''"
	);
	$places = array();
	foreach ( (array) $rows as $r ) {
		$city = trim( $r->city );
		$prov = strtoupper( trim( (string) $r->prov ) );
		if ( '' === $city ) {
			continue;
		}
		$places[ $city ] = $prov;
	}
	ksort( $places, SORT_NATURAL | SORT_FLAG_CASE );
	set_transient( 'mep_cal_places', $places, 6 * HOUR_IN_SECONDS );
	return $places;
}
add_action( 'save_post_tribe_venue', function () {
	delete_transient( 'mep_cal_places' );
} );

/** ID dei luoghi che corrispondono ai filtri; null = nessun filtro. */
function mep_cal_venue_ids( $prov, $city ) {
	if ( '' === $prov && '' === $city ) {
		return null;
	}
	global $wpdb;
	$sql  = "SELECT DISTINCT p.ID FROM {$wpdb->posts} p";
	$args = array();
	if ( '' !== $city ) {
		$sql   .= " JOIN {$wpdb->postmeta} c ON c.post_id = p.ID AND c.meta_key = '_VenueCity' AND c.meta_value = %s";
		$args[] = $city;
	}
	if ( '' !== $prov ) {
		$sql   .= " JOIN {$wpdb->postmeta} pr ON pr.post_id = p.ID AND pr.meta_key IN ('_VenueProvince','_VenueStateProvince') AND pr.meta_value = %s";
		$args[] = $prov;
	}
	$sql .= " WHERE p.post_type = 'tribe_venue' AND p.post_status = 'publish'";
	// phpcs:ignore WordPress.DB.DirectDatabaseQuery, WordPress.DB.PreparedSQL.NotPrepared
	$ids = $wpdb->get_col( $wpdb->prepare( $sql, $args ) );
	return array_map( 'intval', (array) $ids );
}

/** Eventi pubblicati che si sovrappongono all'intervallo [from, to]. */
function mep_cal_events( DateTime $from, DateTime $to, $venue_ids, $q, $limit = 300 ) {
	if ( is_array( $venue_ids ) && empty( $venue_ids ) ) {
		return array();
	}
	if ( function_exists( 'tribe_events' ) ) {
		$repo = tribe_events()
			->where( 'status', 'publish' )
			->where( 'date_overlaps', $from->format( 'Y-m-d 00:00:00' ), $to->format( 'Y-m-d 23:59:59' ) )
			->order_by( 'event_date', 'ASC' )
			->per_page( $limit );
		if ( is_array( $venue_ids ) ) {
			$repo->where( 'venue', $venue_ids );
		}
		if ( '' !== $q ) {
			$repo->search( $q );
		}
		return mep_cal_in_range( $repo->all(), $from, $to );
	}
	$args = array(
		'posts_per_page' => $limit,
		'start_date'     => $from->format( 'Y-m-d 00:00:00' ),
		'end_date'       => $to->format( 'Y-m-d 23:59:59' ),
		'eventDisplay'   => 'custom',
		'post_status'    => 'publish',
	);
	if ( '' !== $q ) {
		$args['s'] = $q;
	}
	if ( is_array( $venue_ids ) ) {
		$args['venue'] = $venue_ids;
	}
	return mep_cal_in_range( tribe_get_events( $args ), $from, $to );
}

/** Sicurezza: tiene solo gli eventi che toccano davvero l'intervallo. */
function mep_cal_in_range( $events, DateTime $from, DateTime $to ) {
	$f   = $from->format( 'Y-m-d' );
	$t   = $to->format( 'Y-m-d' );
	$out = array();
	foreach ( (array) $events as $ev ) {
		if ( tribe_get_end_date( $ev, false, 'Y-m-d' ) >= $f && tribe_get_start_date( $ev, false, 'Y-m-d' ) <= $t ) {
			$out[] = $ev;
		}
	}
	return $out;
}

function mep_cal_url( $over = array() ) {
	$base = array(
		'cal_vista'  => mep_cal_param( 'cal_vista', 'mese' ),
		'cal_data'   => mep_cal_param( 'cal_data' ),
		'cal_prov'   => mep_cal_param( 'cal_prov' ),
		'cal_comune' => mep_cal_param( 'cal_comune' ),
		'cal_q'      => mep_cal_param( 'cal_q' ),
	);
	$q = array_filter( array_merge( $base, $over ), 'strlen' );
	return esc_url( add_query_arg( $q, get_permalink() ) . '#mep-cal' );
}

function mep_cal_ev_days( $ev ) {
	$tz = wp_timezone();
	$s  = new DateTime( tribe_get_start_date( $ev, false, 'Y-m-d' ), $tz );
	$e  = new DateTime( tribe_get_end_date( $ev, false, 'Y-m-d' ), $tz );
	return array( $s, $e, (int) $s->diff( $e )->days );
}

function mep_cal_item( $ev, $show_date = false ) {
	$time = ( function_exists( 'tribe_event_is_all_day' ) && tribe_event_is_all_day( $ev ) ) ? '' : tribe_get_start_date( $ev, false, 'H:i' );
	list( $s, $e, $span ) = mep_cal_ev_days( $ev );
	$when = array();
	if ( $show_date || $span > 0 ) {
		$when[] = $span > 0 ? 'dal ' . wp_date( 'j M', $s->getTimestamp() ) . ' al ' . wp_date( 'j M', $e->getTimestamp() ) : wp_date( 'j M', $s->getTimestamp() );
	}
	if ( $time ) {
		$when[] = $time;
	}
	$city = function_exists( 'tribe_get_city' ) ? tribe_get_city( $ev ) : '';
	$img  = get_the_post_thumbnail_url( $ev, 'thumbnail' );
	$out  = '<li class="mep-cal__ev"><a href="' . esc_url( get_permalink( $ev ) ) . '">';
	$out .= $img ? '<img src="' . esc_url( $img ) . '" alt="" loading="lazy" decoding="async" width="64" height="64">' : '<span class="mep-cal__noimg"></span>';
	$out .= '<span class="mep-cal__txt"><strong>' . esc_html( get_the_title( $ev ) ) . '</strong>';
	$out .= '<span class="mep-cal__meta">' . esc_html( implode( ' · ', array_filter( array( implode( ', ', $when ), $city ) ) ) ) . '</span></span></a></li>';
	return $out;
}

/** Elenco per giorno: eventi lunghi (> 7 giorni) a parte, "in corso". */
function mep_cal_agenda( $events, DateTime $from, DateTime $to ) {
	$long  = array();
	$byday = array();
	foreach ( $events as $ev ) {
		list( $s, $e, $span ) = mep_cal_ev_days( $ev );
		if ( $span > 7 ) {
			$long[] = $ev;
			continue;
		}
		$d = max( $s, $from );
		$d = clone $d;
		while ( $d <= $e && $d <= $to ) {
			$byday[ $d->format( 'Y-m-d' ) ][] = $ev;
			$d->modify( '+1 day' );
		}
	}
	ksort( $byday );
	$out = '';
	foreach ( $byday as $day => $list ) {
		$ts   = strtotime( $day );
		$out .= '<h3 class="mep-cal__day">' . esc_html( ucfirst( wp_date( 'l j F', $ts ) ) ) . '</h3><ul class="mep-cal__list">';
		foreach ( $list as $ev ) {
			$out .= mep_cal_item( $ev );
		}
		$out .= '</ul>';
	}
	if ( $long ) {
		$out .= '<h3 class="mep-cal__day">Mostre e rassegne in corso</h3><ul class="mep-cal__list">';
		foreach ( $long as $ev ) {
			$out .= mep_cal_item( $ev, true );
		}
		$out .= '</ul>';
	}
	return $out ? $out : '<p class="mep-cal__empty">Nessun evento trovato con questi filtri.</p>';
}

function mep_cal_month_grid( $events, DateTime $first ) {
	$last   = ( clone $first )->modify( 'last day of this month' );
	$cells  = array();
	foreach ( $events as $ev ) {
		list( $s, $e, $span ) = mep_cal_ev_days( $ev );
		if ( $span > 7 ) {
			continue;
		}
		$d = max( $s, $first );
		$d = clone $d;
		while ( $d <= $e && $d <= $last ) {
			$cells[ $d->format( 'Y-m-d' ) ][] = $ev;
			$d->modify( '+1 day' );
		}
	}
	$today = current_time( 'Y-m-d' );
	$out   = '<div class="mep-cal__grid" role="table"><div class="mep-cal__wd">';
	foreach ( array( 'Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom' ) as $w ) {
		$out .= '<span>' . $w . '</span>';
	}
	$out .= '</div><div class="mep-cal__cells">';
	$lead = (int) $first->format( 'N' ) - 1;
	for ( $i = 0; $i < $lead; $i++ ) {
		$out .= '<div class="mep-cal__cell mep-cal__cell--out"></div>';
	}
	$d = clone $first;
	while ( $d <= $last ) {
		$k    = $d->format( 'Y-m-d' );
		$list = $cells[ $k ] ?? array();
		$cls  = 'mep-cal__cell' . ( $k === $today ? ' mep-cal__cell--today' : '' ) . ( $list ? ' mep-cal__cell--has' : '' );
		$out .= '<div class="' . $cls . '"><a class="mep-cal__num" href="' . mep_cal_url( array( 'cal_vista' => 'giorno', 'cal_data' => $k ) ) . '">' . $d->format( 'j' ) . '</a>';
		foreach ( array_slice( $list, 0, 3 ) as $ev ) {
			$out .= '<a class="mep-cal__chip" href="' . esc_url( get_permalink( $ev ) ) . '" title="' . esc_attr( get_the_title( $ev ) ) . '">' . esc_html( wp_trim_words( get_the_title( $ev ), 6, '…' ) ) . '</a>';
		}
		if ( count( $list ) > 3 ) {
			$out .= '<a class="mep-cal__more" href="' . mep_cal_url( array( 'cal_vista' => 'giorno', 'cal_data' => $k ) ) . '">+' . ( count( $list ) - 3 ) . ' altri</a>';
		}
		$out .= '</div>';
		$d->modify( '+1 day' );
	}
	$out .= '</div></div>';
	return $out;
}

function mep_cal_shortcode() {
	if ( ! function_exists( 'tribe_get_events' ) ) {
		return '';
	}
	$tz    = wp_timezone();
	$vista = mep_cal_param( 'cal_vista', 'mese' );
	if ( ! in_array( $vista, array( 'giorno', 'settimana', 'mese', 'prossimi' ), true ) ) {
		$vista = 'mese';
	}
	$data_s = mep_cal_param( 'cal_data' );
	$ref    = preg_match( '/^\d{4}-\d{2}-\d{2}$/', $data_s ) ? DateTime::createFromFormat( '!Y-m-d', $data_s, $tz ) : new DateTime( current_time( 'Y-m-d' ), $tz );
	if ( ! $ref ) {
		$ref = new DateTime( current_time( 'Y-m-d' ), $tz );
	}
	$prov   = strtoupper( mep_cal_param( 'cal_prov' ) );
	$city   = mep_cal_param( 'cal_comune' );
	$q      = mep_cal_param( 'cal_q' );
	$places = mep_cal_places();
	if ( '' !== $city && '' === $prov && isset( $places[ $city ] ) ) {
		$prov = $places[ $city ];
	}

	switch ( $vista ) {
		case 'giorno':
			$from  = clone $ref;
			$to    = clone $ref;
			$prev  = ( clone $ref )->modify( '-1 day' );
			$next  = ( clone $ref )->modify( '+1 day' );
			$label = ucfirst( wp_date( 'l j F Y', $ref->getTimestamp() ) );
			break;
		case 'settimana':
			$from  = ( clone $ref )->modify( 'monday this week' );
			$to    = ( clone $from )->modify( '+6 days' );
			$prev  = ( clone $from )->modify( '-7 days' );
			$next  = ( clone $from )->modify( '+7 days' );
			$label = 'Settimana dal ' . wp_date( 'j F', $from->getTimestamp() ) . ' al ' . wp_date( 'j F Y', $to->getTimestamp() );
			break;
		case 'prossimi':
			$from  = new DateTime( current_time( 'Y-m-d' ), $tz );
			$to    = ( clone $from )->modify( '+90 days' );
			$prev  = null;
			$next  = null;
			$label = 'Prossimi eventi';
			break;
		default:
			$from  = ( clone $ref )->modify( 'first day of this month' );
			$to    = ( clone $from )->modify( 'last day of this month' );
			$prev  = ( clone $from )->modify( '-1 month' );
			$next  = ( clone $from )->modify( '+1 month' );
			$label = ucfirst( wp_date( 'F Y', $from->getTimestamp() ) );
	}

	$events = mep_cal_events( $from, $to, mep_cal_venue_ids( $prov, $city ), $q, 'prossimi' === $vista ? 80 : 300 );

	ob_start();
	echo mep_eventi_css(); // phpcs:ignore WordPress.Security.EscapeOutput
	echo mep_cal_css(); // phpcs:ignore WordPress.Security.EscapeOutput
	echo '<section class="mep-cal" id="mep-cal">';

	// --- filtri
	echo '<form class="mep-cal__filters" method="get" action="' . esc_url( get_permalink() ) . '#mep-cal">';
	echo '<input type="hidden" name="cal_vista" value="' . esc_attr( $vista ) . '">';
	echo '<input type="hidden" name="cal_data" value="' . esc_attr( $ref->format( 'Y-m-d' ) ) . '">';
	echo '<input type="search" name="cal_q" value="' . esc_attr( $q ) . '" placeholder="Cerca un evento…" aria-label="Cerca un evento">';
	echo '<select name="cal_prov" aria-label="Provincia" onchange="mepCalProv(this)"><option value="">Tutte le province</option>';
	foreach ( MEP_CAL_PROV as $code => $name ) {
		echo '<option value="' . esc_attr( $code ) . '"' . selected( $prov, $code, false ) . '>' . esc_html( strtoupper( $name ) ) . '</option>';
	}
	echo '</select><select name="cal_comune" aria-label="Comune"><option value="">Tutti i comuni</option>';
	foreach ( $places as $c => $p ) {
		$hidden = ( '' !== $prov && $p !== $prov ) ? ' hidden disabled' : '';
		echo '<option value="' . esc_attr( $c ) . '" data-prov="' . esc_attr( $p ) . '"' . selected( $city, $c, false ) . $hidden . '>' . esc_html( $c ) . '</option>';
	}
	echo '</select><button type="submit">Cerca</button>';
	if ( '' !== $q || '' !== $prov || '' !== $city ) {
		echo ' <a class="mep-cal__reset" href="' . esc_url( add_query_arg( 'cal_vista', $vista, get_permalink() ) . '#mep-cal' ) . '">Azzera filtri</a>';
	}
	echo '</form>';

	// --- viste e navigazione
	echo '<div class="mep-cal__bar"><nav class="mep-cal__views">';
	foreach ( array( 'giorno' => 'Giorno', 'settimana' => 'Settimana', 'mese' => 'Mese', 'prossimi' => 'Prossimi' ) as $k => $l ) {
		echo '<a href="' . mep_cal_url( array( 'cal_vista' => $k ) ) . '"' . ( $k === $vista ? ' class="on" aria-current="page"' : '' ) . '>' . esc_html( $l ) . '</a>'; // phpcs:ignore WordPress.Security.EscapeOutput
	}
	echo '</nav><div class="mep-cal__nav">';
	if ( $prev ) {
		echo '<a href="' . mep_cal_url( array( 'cal_data' => $prev->format( 'Y-m-d' ) ) ) . '" aria-label="Precedente">‹</a>'; // phpcs:ignore WordPress.Security.EscapeOutput
	}
	echo '<strong>' . esc_html( $label ) . '</strong>';
	if ( $next ) {
		echo '<a href="' . mep_cal_url( array( 'cal_data' => $next->format( 'Y-m-d' ) ) ) . '" aria-label="Successivo">›</a>'; // phpcs:ignore WordPress.Security.EscapeOutput
	}
	echo '<a class="mep-cal__today" href="' . mep_cal_url( array( 'cal_data' => current_time( 'Y-m-d' ) ) ) . '">Oggi</a>'; // phpcs:ignore WordPress.Security.EscapeOutput
	echo '</div></div>';

	$count = count( $events );
	echo '<p class="mep-cal__count">' . esc_html( $count ? sprintf( _n( '%d evento', '%d eventi', $count, 'mep-eventi' ), $count ) : 'Nessun evento' );
	if ( '' !== $city ) {
		echo esc_html( ' a ' . $city );
	} elseif ( '' !== $prov ) {
		echo esc_html( ' in provincia di ' . ( MEP_CAL_PROV[ $prov ] ?? $prov ) );
	}
	echo '</p>';

	if ( 'mese' === $vista ) {
		echo mep_cal_month_grid( $events, $from ); // phpcs:ignore WordPress.Security.EscapeOutput
		echo '<div class="mep-cal__agenda mep-cal__agenda--month">' . mep_cal_agenda( $events, $from, $to ) . '</div>'; // phpcs:ignore WordPress.Security.EscapeOutput
	} else {
		echo '<div class="mep-cal__agenda">' . mep_cal_agenda( $events, $from, $to ) . '</div>'; // phpcs:ignore WordPress.Security.EscapeOutput
	}

	$submit = mep_eventi_opt( 'submit_page_url' );
	if ( $submit ) {
		echo '<p class="mep-ev__actions"><a class="mep-ev__btn mep-ev__btn--primary" href="' . esc_url( $submit ) . '">Segnala il tuo evento</a></p>';
	}
	echo '</section>';
	echo '<script>function mepCalProv(s){var c=s.form.cal_comune,p=s.value;for(var i=1;i<c.options.length;i++){var o=c.options[i],ok=!p||o.dataset.prov===p;o.hidden=!ok;o.disabled=!ok;if(!ok&&o.selected)c.selectedIndex=0;}}</script>';
	return ob_get_clean();
}

function mep_cal_css() {
	return '<style id="mep-cal-css">
.mep-cal{--a:#2f6f4f;margin:0 0 2em}
.mep-cal__filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.mep-cal__filters input[type=search]{flex:1 1 220px;min-width:180px}
.mep-cal__filters input,.mep-cal__filters select{padding:.5em .7em;border:1px solid rgba(0,0,0,.25);border-radius:8px;font:inherit;background:#fff}
.mep-cal__filters button{background:var(--a);color:#fff;border:0;border-radius:8px;padding:.55em 1.1em;font-weight:700;cursor:pointer}
.mep-cal__reset{font-size:.9em}
.mep-cal__bar{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px;margin:6px 0 8px}
.mep-cal__views{display:flex;border:1px solid var(--a);border-radius:8px;overflow:hidden}
.mep-cal__views a{padding:.45em .9em;text-decoration:none;color:var(--a);font-weight:600}
.mep-cal__views a.on{background:var(--a);color:#fff}
.mep-cal__nav{display:flex;align-items:center;gap:10px}
.mep-cal__nav a{text-decoration:none;font-size:1.4em;line-height:1;color:var(--a);padding:0 .2em}
.mep-cal__nav a.mep-cal__today{font-size:.9em;border:1px solid var(--a);border-radius:6px;padding:.3em .7em}
.mep-cal__count{opacity:.7;font-size:.9em;margin:4px 0 10px}
.mep-cal__grid{border:1px solid rgba(0,0,0,.12);border-radius:10px;overflow:hidden;margin-bottom:18px}
.mep-cal__wd,.mep-cal__cells{display:grid;grid-template-columns:repeat(7,1fr)}
.mep-cal__wd span{padding:6px;font-size:.8em;font-weight:700;text-align:center;background:#f3f5f3}
.mep-cal__cell{min-height:96px;border-top:1px solid rgba(0,0,0,.08);border-left:1px solid rgba(0,0,0,.08);padding:4px;display:flex;flex-direction:column;gap:3px;overflow:hidden}
.mep-cal__cell:nth-child(7n+1){border-left:0}
.mep-cal__cell--out{background:#fafafa}
.mep-cal__cell--today{background:#eef6f1}
.mep-cal__num{font-weight:700;font-size:.85em;text-decoration:none;color:inherit}
.mep-cal__chip{display:block;font-size:.75em;line-height:1.25;padding:2px 4px;border-radius:4px;background:#e6f0ea;color:#1e4a33;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mep-cal__more{font-size:.72em;color:var(--a)}
.mep-cal__day{font-size:1.05em;margin:18px 0 6px;padding-bottom:4px;border-bottom:2px solid var(--a)}
.mep-cal__list{list-style:none;margin:0;padding:0}
.mep-cal__ev a{display:flex;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid rgba(0,0,0,.07);text-decoration:none;color:inherit}
.mep-cal__ev img,.mep-cal__noimg{width:64px;height:64px;object-fit:cover;border-radius:8px;flex:0 0 64px;background:#eef1ee}
.mep-cal__txt{display:flex;flex-direction:column;gap:2px}
.mep-cal__meta{font-size:.85em;opacity:.75}
.mep-cal__empty{padding:16px;background:#f6f7f6;border-radius:8px}
.mep-cal__agenda--month{display:none}
@media (max-width:767px){.mep-cal__grid{display:none}.mep-cal__agenda--month{display:block}.mep-cal__bar{flex-direction:column;align-items:stretch}.mep-cal__views{justify-content:space-between}.mep-cal__views a{flex:1;text-align:center;padding:.5em .3em}.mep-cal__nav{justify-content:space-between}}
</style>';
}
