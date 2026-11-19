<?php
/**
 * Plugin Name:       MEP Eventi – Prossimi eventi e segnalazioni
 * Description:       Calendario eventi con filtri ([mep_calendario]), box "Prossimi eventi" leggero per la home ([mep_prossimi_eventi]) e modulo pubblico per segnalare eventi ([mep_segnala_evento]) che crea bozze in The Events Calendar.
 * Version:           1.1.3
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            Montagne & Paesi
 * License:           GPL-2.0-or-later
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'MEP_EVENTI_VERSION', '1.1.3' );
require_once __DIR__ . '/includes/calendario.php';
define( 'MEP_EVENTI_OPT', 'mep_eventi_settings' );

/* -------------------------------------------------------------------------
 * Impostazioni
 * ---------------------------------------------------------------------- */

function mep_eventi_defaults() {
	return array(
		'notify_email'    => get_option( 'admin_email' ),
		'notify_submitter'=> 1,
		'submit_page_url' => '',
		'privacy_url'     => function_exists( 'get_privacy_policy_url' ) ? get_privacy_policy_url() : '',
		'thanks_message'  => 'Grazie! La tua segnalazione è arrivata in redazione: la controlliamo e, se adatta, la pubblichiamo nel calendario.',
		'reader_tag'      => 'Segnalato dai lettori',
		'turnstile_site'  => '',
		'turnstile_secret'=> '',
		'max_upload_mb'   => 8,
		'rate_per_hour'   => 5,
	);
}

function mep_eventi_opt( $key ) {
	$o = wp_parse_args( (array) get_option( MEP_EVENTI_OPT, array() ), mep_eventi_defaults() );
	return isset( $o[ $key ] ) ? $o[ $key ] : null;
}

add_action( 'admin_menu', function () {
	add_options_page( 'MEP Eventi', 'MEP Eventi', 'manage_options', 'mep-eventi', 'mep_eventi_settings_page' );
} );

add_action( 'admin_init', function () {
	register_setting( 'mep_eventi', MEP_EVENTI_OPT, array(
		'type'              => 'array',
		'sanitize_callback' => 'mep_eventi_sanitize_settings',
		'default'           => mep_eventi_defaults(),
	) );
} );

function mep_eventi_sanitize_settings( $in ) {
	$d   = mep_eventi_defaults();
	$out = array();
	$out['notify_email']     = sanitize_email( $in['notify_email'] ?? $d['notify_email'] );
	$out['notify_submitter'] = empty( $in['notify_submitter'] ) ? 0 : 1;
	$out['submit_page_url']  = esc_url_raw( $in['submit_page_url'] ?? '' );
	$out['privacy_url']      = esc_url_raw( $in['privacy_url'] ?? '' );
	$out['thanks_message']   = sanitize_textarea_field( $in['thanks_message'] ?? $d['thanks_message'] );
	$out['reader_tag']       = sanitize_text_field( $in['reader_tag'] ?? $d['reader_tag'] );
	$out['turnstile_site']   = sanitize_text_field( $in['turnstile_site'] ?? '' );
	$out['turnstile_secret'] = sanitize_text_field( $in['turnstile_secret'] ?? '' );
	$out['max_upload_mb']    = max( 1, min( 20, (int) ( $in['max_upload_mb'] ?? 8 ) ) );
	$out['rate_per_hour']    = max( 1, min( 50, (int) ( $in['rate_per_hour'] ?? 5 ) ) );
	return $out;
}

function mep_eventi_settings_page() {
	$o = wp_parse_args( (array) get_option( MEP_EVENTI_OPT, array() ), mep_eventi_defaults() );
	$n = MEP_EVENTI_OPT;
	?>
	<div class="wrap">
		<h1>MEP Eventi</h1>
		<p>Shortcode: <code>[mep_prossimi_eventi numero="6"]</code> per la home, <code>[mep_segnala_evento]</code> per la pagina "Segnala un evento".</p>
		<form method="post" action="options.php">
			<?php settings_fields( 'mep_eventi' ); ?>
			<table class="form-table" role="presentation">
				<tr><th>Email per le segnalazioni</th><td><input type="email" class="regular-text" name="<?php echo esc_attr( $n ); ?>[notify_email]" value="<?php echo esc_attr( $o['notify_email'] ); ?>"></td></tr>
				<tr><th>Conferma al segnalatore</th><td><label><input type="checkbox" name="<?php echo esc_attr( $n ); ?>[notify_submitter]" value="1" <?php checked( $o['notify_submitter'] ); ?>> invia un'email di conferma a chi segnala</label></td></tr>
				<tr><th>Pagina "Segnala un evento"</th><td><input type="url" class="regular-text" name="<?php echo esc_attr( $n ); ?>[submit_page_url]" value="<?php echo esc_attr( $o['submit_page_url'] ); ?>" placeholder="https://www.montagneepaesi.com/segnala-un-evento/"><p class="description">Usata per il pulsante sotto i prossimi eventi.</p></td></tr>
				<tr><th>Pagina privacy</th><td><input type="url" class="regular-text" name="<?php echo esc_attr( $n ); ?>[privacy_url]" value="<?php echo esc_attr( $o['privacy_url'] ); ?>"></td></tr>
				<tr><th>Messaggio di ringraziamento</th><td><textarea class="large-text" rows="3" name="<?php echo esc_attr( $n ); ?>[thanks_message]"><?php echo esc_textarea( $o['thanks_message'] ); ?></textarea></td></tr>
				<tr><th>Tag per le segnalazioni</th><td><input type="text" class="regular-text" name="<?php echo esc_attr( $n ); ?>[reader_tag]" value="<?php echo esc_attr( $o['reader_tag'] ); ?>"></td></tr>
				<tr><th>Cloudflare Turnstile (facoltativo)</th><td>
					<input type="text" class="regular-text" placeholder="Site key" name="<?php echo esc_attr( $n ); ?>[turnstile_site]" value="<?php echo esc_attr( $o['turnstile_site'] ); ?>"><br>
					<input type="password" class="regular-text" placeholder="Secret key" name="<?php echo esc_attr( $n ); ?>[turnstile_secret]" value="<?php echo esc_attr( $o['turnstile_secret'] ); ?>">
					<p class="description">Anti-spam gratuito. Senza chiavi restano attivi honeypot, controllo dei tempi e limite per IP.</p></td></tr>
				<tr><th>Locandina: dimensione massima (MB)</th><td><input type="number" min="1" max="20" name="<?php echo esc_attr( $n ); ?>[max_upload_mb]" value="<?php echo esc_attr( $o['max_upload_mb'] ); ?>"></td></tr>
				<tr><th>Segnalazioni per ora da uno stesso IP</th><td><input type="number" min="1" max="50" name="<?php echo esc_attr( $n ); ?>[rate_per_hour]" value="<?php echo esc_attr( $o['rate_per_hour'] ); ?>"></td></tr>
			</table>
			<?php submit_button(); ?>
		</form>
	</div>
	<?php
}

/* -------------------------------------------------------------------------
 * robots.txt: limita i bot che consumano risorse senza portare lettori
 * (disattivabile con: add_filter( 'mep_eventi_robots_rules', '__return_empty_string' ); )
 * ---------------------------------------------------------------------- */

add_filter( 'robots_txt', 'mep_eventi_robots_txt', 99, 2 );

function mep_eventi_robots_txt( $output, $public ) {
	if ( ! $public ) {
		return $output;
	}
	$blocked = array(
		// addestramento IA (non portano visite)
		'GPTBot', 'ClaudeBot', 'anthropic-ai', 'CCBot', 'Bytespider', 'Amazonbot', 'meta-externalagent',
		'Google-Extended', 'Applebot-Extended', 'PerplexityBot', 'cohere-ai', 'Diffbot',
		// SEO / monitoraggio commerciali
		'AhrefsBot', 'SemrushBot', 'MJ12bot', 'DotBot', 'BLEXBot', 'DataForSeoBot', 'trendictionbot', 'tphotobot',
		// motori non rilevanti per un sito locale italiano
		'Baiduspider', 'YandexBot', 'PetalBot', 'Sogou',
	);
	$rules  = "\n# --- MEP: bot bloccati per alleggerire il server ---\n";
	foreach ( $blocked as $bot ) {
		$rules .= "User-agent: {$bot}\nDisallow: /\n\n";
	}
	$rules .= "# --- MEP: pagine pesanti e senza valore per i motori ---\n";
	$rules .= "User-agent: *\nDisallow: /*?print=\nDisallow: /*&print=\nDisallow: /*?noamp=\nDisallow: /wp-json/oembed/\nDisallow: /*?p=\nDisallow: /?s=\n";
	$rules = apply_filters( 'mep_eventi_robots_rules', $rules );
	return $output . $rules;
}

/* -------------------------------------------------------------------------
 * Traduzioni mancanti di The Events Calendar (titoli tipo "Eventi from 18 Novembre – 22 Novembre")
 * ---------------------------------------------------------------------- */

add_filter( 'gettext_the-events-calendar', 'mep_eventi_fix_tec_strings', 10, 2 );
add_filter( 'gettext_tribe-common', 'mep_eventi_fix_tec_strings', 10, 2 );

function mep_eventi_fix_tec_strings( $translation, $text ) {
	if ( $translation !== $text ) {
		return $translation; // già tradotta
	}
	$map = array(
		' from '    => ' dal ',
		' for '     => ' per ',
		'Upcoming ' => 'Prossimi ',
		'Past '     => 'Passati ',
	);
	if ( false === strpos( $text, '%' ) ) {
		return $translation; // solo frasi con segnaposto (i titoli), per non toccare altro
	}
	return strtr( $translation, $map );
}

/* -------------------------------------------------------------------------
 * Stili (stampati una sola volta, solo dove serve)
 * ---------------------------------------------------------------------- */

function mep_eventi_css() {
	static $done = false;
	if ( $done ) {
		return '';
	}
	$done = true;
	return '<style id="mep-eventi-css">
.mep-ev{--mep-accent:#2f6f4f;margin:0 0 1.5em}
.mep-ev__head{display:flex;align-items:baseline;justify-content:space-between;gap:1em;margin-bottom:.8em;flex-wrap:wrap}
.mep-ev__title{margin:0;font-size:1.4em}
.mep-ev__grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
.mep-ev__card{display:flex;flex-direction:column;border:1px solid rgba(0,0,0,.1);border-radius:10px;overflow:hidden;background:#fff;color:inherit;text-decoration:none;transition:box-shadow .2s}
.mep-ev__card:hover{box-shadow:0 4px 16px rgba(0,0,0,.08)}
.mep-ev__img{position:relative;aspect-ratio:4/3;background:#eef1ee}
.mep-ev__img img{width:100%;height:100%;object-fit:cover;display:block}
.mep-ev__date{position:absolute;top:10px;left:10px;background:#fff;border-radius:8px;padding:4px 9px;text-align:center;line-height:1.1;box-shadow:0 1px 4px rgba(0,0,0,.15)}
.mep-ev__day{display:block;font-size:1.35em;font-weight:700;color:var(--mep-accent)}
.mep-ev__mon{display:block;font-size:.72em;text-transform:uppercase;letter-spacing:.05em}
.mep-ev__body{padding:10px 12px 12px}
.mep-ev__name{font-weight:700;line-height:1.3;margin:0 0 .3em;font-size:1em}
.mep-ev__meta{font-size:.85em;opacity:.75}
.mep-ev__list{list-style:none;margin:0;padding:0}
.mep-ev__list li{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid rgba(0,0,0,.08)}
.mep-ev__list .mep-ev__date{position:static;box-shadow:none;border:1px solid rgba(0,0,0,.1);min-width:52px}
.mep-ev__list a{color:inherit;text-decoration:none}
.mep-ev__actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:1em}
.mep-ev__btn{display:inline-block;padding:.55em 1em;border-radius:8px;border:1px solid var(--mep-accent);color:var(--mep-accent);text-decoration:none;font-weight:600}
.mep-ev__btn--primary{background:var(--mep-accent);color:#fff}
@media (max-width:767px){.mep-ev__grid{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;gap:12px;padding-bottom:8px;-webkit-overflow-scrolling:touch}.mep-ev__card{flex:0 0 72%;scroll-snap-align:start}.mep-ev__title{font-size:1.25em}}
.mep-form{max-width:760px}
.mep-form fieldset{border:1px solid rgba(0,0,0,.12);border-radius:10px;padding:14px 16px;margin:0 0 16px}
.mep-form legend{font-weight:700;padding:0 6px}
.mep-form .mep-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.mep-form label{display:block;font-size:.9em;font-weight:600;margin:6px 0 4px}
.mep-form input[type=text],.mep-form input[type=email],.mep-form input[type=url],.mep-form input[type=date],.mep-form input[type=time],.mep-form input[type=tel],.mep-form select,.mep-form textarea{width:100%;box-sizing:border-box;padding:.55em .7em;border:1px solid rgba(0,0,0,.25);border-radius:6px;font:inherit}
.mep-form textarea{min-height:150px}
.mep-form .mep-help{font-size:.8em;opacity:.7;margin-top:3px}
.mep-form .mep-hp{position:absolute!important;left:-9999px!important;width:1px;height:1px;overflow:hidden}
.mep-form button{background:#2f6f4f;color:#fff;border:0;border-radius:8px;padding:.75em 1.4em;font-weight:700;cursor:pointer;font-size:1em}
.mep-notice{padding:12px 14px;border-radius:8px;margin:0 0 16px}
.mep-notice--ok{background:#e6f4ea;border:1px solid #9fd3ad}
.mep-notice--err{background:#fdecea;border:1px solid #f5b5ae}
</style>';
}

/* -------------------------------------------------------------------------
 * [mep_prossimi_eventi]
 * ---------------------------------------------------------------------- */

add_shortcode( 'mep_prossimi_eventi', 'mep_eventi_shortcode_upcoming' );

function mep_eventi_shortcode_upcoming( $atts ) {
	if ( ! function_exists( 'tribe_get_events' ) ) {
		return current_user_can( 'manage_options' ) ? '<p><em>MEP Eventi: The Events Calendar non è attivo.</em></p>' : '';
	}
	$a = shortcode_atts( array(
		'numero'    => 6,
		'titolo'    => 'Prossimi eventi',
		'layout'    => 'griglia', // griglia | lista
		'categoria' => '',        // slug categoria eventi
		'pulsanti'  => 'si',
	), $atts, 'mep_prossimi_eventi' );

	$n      = max( 1, min( 24, (int) $a['numero'] ) );
	$layout = 'lista' === $a['layout'] ? 'lista' : 'griglia';
	$key    = 'mep_ev_' . md5( wp_json_encode( array( $n, $layout, $a['categoria'], $a['titolo'], $a['pulsanti'], get_locale() ) ) );
	$html   = get_transient( $key );
	if ( false === $html ) {
		$html = mep_eventi_render_upcoming( $n, $layout, $a );
		set_transient( $key, $html, 10 * MINUTE_IN_SECONDS );
		$keys   = (array) get_option( 'mep_eventi_cache_keys', array() );
		$keys[] = $key;
		update_option( 'mep_eventi_cache_keys', array_values( array_unique( array_slice( $keys, -50 ) ) ), false );
	}
	return mep_eventi_css() . $html;
}

function mep_eventi_flush_cache() {
	foreach ( (array) get_option( 'mep_eventi_cache_keys', array() ) as $k ) {
		delete_transient( $k );
	}
}
add_action( 'save_post_tribe_events', 'mep_eventi_flush_cache' );
add_action( 'trashed_post', 'mep_eventi_flush_cache' );

function mep_eventi_render_upcoming( $n, $layout, $a ) {
	$args = array(
		'posts_per_page' => $n,
		'start_date'     => current_time( 'Y-m-d H:i:s' ),
		'eventDisplay'   => 'list',
		'post_status'    => 'publish',
	);
	if ( $a['categoria'] ) {
		$args['tax_query'] = array( array( // phpcs:ignore WordPress.DB.SlowDBQuery
			'taxonomy' => 'tribe_events_cat',
			'field'    => 'slug',
			'terms'    => array_map( 'trim', explode( ',', $a['categoria'] ) ),
		) );
	}
	$events = tribe_get_events( $args );

	ob_start();
	echo '<section class="mep-ev mep-ev--' . esc_attr( $layout ) . '">';
	if ( $a['titolo'] ) {
		echo '<div class="mep-ev__head"><h2 class="mep-ev__title">' . esc_html( $a['titolo'] ) . '</h2></div>';
	}
	if ( empty( $events ) ) {
		echo '<p>Al momento non ci sono eventi in programma.</p>';
	} elseif ( 'lista' === $layout ) {
		echo '<ul class="mep-ev__list">';
		foreach ( $events as $ev ) {
			echo '<li>' . mep_eventi_date_badge( $ev ) . '<div><a href="' . esc_url( get_permalink( $ev ) ) . '"><span class="mep-ev__name">' . esc_html( get_the_title( $ev ) ) . '</span></a><div class="mep-ev__meta">' . esc_html( mep_eventi_meta_line( $ev ) ) . '</div></div></li>';
		}
		echo '</ul>';
	} else {
		echo '<div class="mep-ev__grid">';
		foreach ( $events as $ev ) {
			$img = get_the_post_thumbnail_url( $ev, 'medium_large' );
			echo '<a class="mep-ev__card" href="' . esc_url( get_permalink( $ev ) ) . '">';
			echo '<div class="mep-ev__img">';
			if ( $img ) {
				echo '<img src="' . esc_url( $img ) . '" alt="' . esc_attr( get_the_title( $ev ) ) . '" loading="lazy" decoding="async">';
			}
			echo mep_eventi_date_badge( $ev ) . '</div>';
			echo '<div class="mep-ev__body"><h3 class="mep-ev__name">' . esc_html( get_the_title( $ev ) ) . '</h3><div class="mep-ev__meta">' . esc_html( mep_eventi_meta_line( $ev ) ) . '</div></div>';
			echo '</a>';
		}
		echo '</div>';
	}
	if ( 'no' !== $a['pulsanti'] ) {
		echo '<div class="mep-ev__actions">';
		$all = function_exists( 'tribe_get_events_link' ) ? tribe_get_events_link() : home_url( '/eventi/' );
		echo '<a class="mep-ev__btn mep-ev__btn--primary" href="' . esc_url( $all ) . '">Tutti gli eventi</a>';
		$submit = mep_eventi_opt( 'submit_page_url' );
		if ( $submit ) {
			echo '<a class="mep-ev__btn" href="' . esc_url( $submit ) . '">Segnala un evento</a>';
		}
		echo '</div>';
	}
	echo '</section>';
	return ob_get_clean();
}

function mep_eventi_date_badge( $ev ) {
	$ts  = strtotime( tribe_get_start_date( $ev, false, 'Y-m-d' ) );
	$mon = date_i18n( 'M', $ts );
	return '<span class="mep-ev__date"><span class="mep-ev__day">' . esc_html( date_i18n( 'j', $ts ) ) . '</span><span class="mep-ev__mon">' . esc_html( $mon ) . '</span></span>';
}

function mep_eventi_meta_line( $ev ) {
	$parts = array();
	if ( function_exists( 'tribe_event_is_all_day' ) && ! tribe_event_is_all_day( $ev ) ) {
		$parts[] = tribe_get_start_date( $ev, false, 'H:i' );
	}
	$city = function_exists( 'tribe_get_city' ) ? tribe_get_city( $ev ) : '';
	$ven  = function_exists( 'tribe_get_venue' ) ? tribe_get_venue( $ev ) : '';
	if ( $city ) {
		$parts[] = $city;
	} elseif ( $ven ) {
		$parts[] = $ven;
	}
	$start = tribe_get_start_date( $ev, false, 'Y-m-d' );
	$end   = tribe_get_end_date( $ev, false, 'Y-m-d' );
	if ( $end && $end !== $start ) {
		$parts[] = 'fino al ' . date_i18n( 'j M', strtotime( $end ) );
	}
	return implode( ' · ', array_filter( $parts ) );
}

/* -------------------------------------------------------------------------
 * [mep_segnala_evento]
 * ---------------------------------------------------------------------- */

add_shortcode( 'mep_segnala_evento', 'mep_eventi_shortcode_form' );

function mep_eventi_form_token() {
	$t = time();
	return $t . '.' . substr( hash_hmac( 'sha256', (string) $t, wp_salt( 'nonce' ) ), 0, 20 );
}

function mep_eventi_check_token( $token ) {
	$parts = explode( '.', (string) $token );
	if ( 2 !== count( $parts ) ) {
		return false;
	}
	list( $t, $sig ) = $parts;
	$expected = substr( hash_hmac( 'sha256', (string) (int) $t, wp_salt( 'nonce' ) ), 0, 20 );
	if ( ! hash_equals( $expected, $sig ) ) {
		return false;
	}
	$age = time() - (int) $t;
	// almeno 4 secondi per compilare (i bot sono istantanei); fino a 30 giorni perché la pagina può essere in cache
	return $age >= 4 && $age <= 30 * DAY_IN_SECONDS;
}

function mep_eventi_shortcode_form() {
	$out = mep_eventi_css() . '<div id="mep"></div>';
	$st  = isset( $_GET['mep_segnalazione'] ) ? sanitize_key( wp_unslash( $_GET['mep_segnalazione'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification
	if ( 'ok' === $st ) {
		return $out . '<div class="mep-notice mep-notice--ok">' . esc_html( mep_eventi_opt( 'thanks_message' ) ) . '</div>';
	}
	if ( $st ) {
		$msgs = array(
			'campi'   => 'Compila tutti i campi obbligatori.',
			'data'    => 'Controlla le date: l\'evento deve essere futuro e la fine non può precedere l\'inizio.',
			'email'   => 'L\'indirizzo email non è valido.',
			'file'    => 'La locandina non è valida: sono ammessi JPG, PNG, WebP o PDF entro la dimensione massima.',
			'spam'    => 'Non siamo riusciti a verificare l\'invio. Ricarica la pagina e riprova.',
			'troppi'  => 'Hai inviato troppe segnalazioni in poco tempo. Riprova più tardi.',
			'privacy' => 'Per inviare la segnalazione devi accettare l\'informativa privacy.',
			'errore'  => 'Si è verificato un errore. Riprova o scrivici.',
		);
		$out .= '<div class="mep-notice mep-notice--err">' . esc_html( $msgs[ $st ] ?? $msgs['errore'] ) . '</div>';
	}

	$cats = taxonomy_exists( 'tribe_events_cat' ) ? get_terms( array( 'taxonomy' => 'tribe_events_cat', 'hide_empty' => false ) ) : array();
	$ts   = mep_eventi_opt( 'turnstile_site' );
	$max  = (int) mep_eventi_opt( 'max_upload_mb' );
	$priv = mep_eventi_opt( 'privacy_url' );

	ob_start();
	?>
	<form class="mep-form" method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" enctype="multipart/form-data">
		<input type="hidden" name="action" value="mep_segnala_evento">
		<input type="hidden" name="mep_t" value="<?php echo esc_attr( mep_eventi_form_token() ); ?>">
		<input type="hidden" name="mep_back" value="<?php echo esc_url( get_permalink() ); ?>">
		<div class="mep-hp" aria-hidden="true"><label>Lascia vuoto<input type="text" name="mep_sito_web" tabindex="-1" autocomplete="off"></label></div>

		<fieldset><legend>L'evento</legend>
			<label for="mep_titolo">Titolo *</label>
			<input type="text" id="mep_titolo" name="mep_titolo" required maxlength="150">
			<div class="mep-row">
				<div><label for="mep_data_inizio">Data di inizio *</label><input type="date" id="mep_data_inizio" name="mep_data_inizio" required min="<?php echo esc_attr( current_time( 'Y-m-d' ) ); ?>"></div>
				<div><label for="mep_ora_inizio">Ora di inizio</label><input type="time" id="mep_ora_inizio" name="mep_ora_inizio"></div>
				<div><label for="mep_data_fine">Data di fine</label><input type="date" id="mep_data_fine" name="mep_data_fine" min="<?php echo esc_attr( current_time( 'Y-m-d' ) ); ?>"></div>
				<div><label for="mep_ora_fine">Ora di fine</label><input type="time" id="mep_ora_fine" name="mep_ora_fine"></div>
			</div>
			<div class="mep-help">Senza ora di inizio l'evento viene indicato come "tutto il giorno".</div>
			<?php if ( ! is_wp_error( $cats ) && $cats ) : ?>
				<label for="mep_categoria">Categoria</label>
				<select id="mep_categoria" name="mep_categoria"><option value="">— scegli —</option>
					<?php foreach ( $cats as $c ) : ?><option value="<?php echo esc_attr( $c->term_id ); ?>"><?php echo esc_html( $c->name ); ?></option><?php endforeach; ?>
				</select>
			<?php endif; ?>
			<label for="mep_descrizione">Descrizione *</label>
			<textarea id="mep_descrizione" name="mep_descrizione" required maxlength="6000" placeholder="Cosa succede, programma, a chi è rivolto…"></textarea>
			<div class="mep-row">
				<div><label for="mep_costo">Costo</label><input type="text" id="mep_costo" name="mep_costo" maxlength="100" placeholder="Es. ingresso libero, 10 €"></div>
				<div><label for="mep_link">Link per informazioni</label><input type="url" id="mep_link" name="mep_link" maxlength="300" placeholder="https://"></div>
			</div>
			<label for="mep_locandina">Locandina</label>
			<input type="file" id="mep_locandina" name="mep_locandina" accept=".jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf">
			<div class="mep-help">JPG, PNG, WebP o PDF, massimo <?php echo (int) $max; ?> MB.</div>
		</fieldset>

		<fieldset><legend>Dove</legend>
			<div class="mep-row">
				<div><label for="mep_comune">Comune *</label><input type="text" id="mep_comune" name="mep_comune" required maxlength="80"></div>
				<div><label for="mep_luogo">Luogo</label><input type="text" id="mep_luogo" name="mep_luogo" maxlength="120" placeholder="Es. Piazza dell'Orologio, Auditorium"></div>
			</div>
			<label for="mep_indirizzo">Indirizzo</label>
			<input type="text" id="mep_indirizzo" name="mep_indirizzo" maxlength="160">
		</fieldset>

		<fieldset><legend>Organizzatore (pubblico)</legend>
			<div class="mep-row">
				<div><label for="mep_org">Nome</label><input type="text" id="mep_org" name="mep_org" maxlength="120" placeholder="Pro Loco, associazione…"></div>
				<div><label for="mep_org_tel">Telefono</label><input type="tel" id="mep_org_tel" name="mep_org_tel" maxlength="40"></div>
				<div><label for="mep_org_email">Email</label><input type="email" id="mep_org_email" name="mep_org_email" maxlength="120"></div>
			</div>
		</fieldset>

		<fieldset><legend>I tuoi dati (non pubblicati)</legend>
			<div class="mep-row">
				<div><label for="mep_nome">Nome e cognome *</label><input type="text" id="mep_nome" name="mep_nome" required maxlength="100"></div>
				<div><label for="mep_email">Email *</label><input type="email" id="mep_email" name="mep_email" required maxlength="120"></div>
			</div>
			<label><input type="checkbox" name="mep_privacy" value="1" required> Ho letto <?php echo $priv ? '<a href="' . esc_url( $priv ) . '" target="_blank" rel="noopener">l\'informativa privacy</a>' : 'l\'informativa privacy'; ?> e acconsento al trattamento dei dati per gestire la segnalazione. *</label>
		</fieldset>

		<?php if ( $ts ) : ?>
			<div class="cf-turnstile" data-sitekey="<?php echo esc_attr( $ts ); ?>" data-language="it"></div>
			<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
		<?php endif; ?>
		<p><button type="submit">Invia la segnalazione</button></p>
		<p class="mep-help">La segnalazione è gratuita. La redazione la controlla prima di pubblicarla e può modificarne il testo.</p>
	</form>
	<?php
	return $out . ob_get_clean();
}

add_action( 'admin_post_nopriv_mep_segnala_evento', 'mep_eventi_handle_submit' );
add_action( 'admin_post_mep_segnala_evento', 'mep_eventi_handle_submit' );

function mep_eventi_redirect( $back, $code ) {
	$back = $back ? $back : home_url( '/' );
	wp_safe_redirect( add_query_arg( 'mep_segnalazione', $code, $back ) . '#mep' );
	exit;
}

function mep_eventi_field( $name, $type = 'text' ) {
	$v = isset( $_POST[ $name ] ) ? wp_unslash( $_POST[ $name ] ) : ''; // phpcs:ignore WordPress.Security.NonceVerification, WordPress.Security.ValidatedSanitizedInput
	switch ( $type ) {
		case 'textarea':
			return trim( sanitize_textarea_field( $v ) );
		case 'email':
			return trim( sanitize_email( $v ) );
		case 'url':
			return trim( esc_url_raw( $v ) );
		default:
			return trim( sanitize_text_field( $v ) );
	}
}

function mep_eventi_client_ip() {
	return isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : '0';
}

function mep_eventi_handle_submit() {
	$back = mep_eventi_field( 'mep_back', 'url' );
	$back = wp_validate_redirect( $back, home_url( '/' ) );

	// --- anti-spam
	if ( '' !== mep_eventi_field( 'mep_sito_web' ) || ! mep_eventi_check_token( mep_eventi_field( 'mep_t' ) ) ) {
		mep_eventi_redirect( $back, 'spam' );
	}
	$secret = mep_eventi_opt( 'turnstile_secret' );
	if ( $secret ) {
		$resp = wp_remote_post( 'https://challenges.cloudflare.com/turnstile/v0/siteverify', array(
			'timeout' => 10,
			'body'    => array(
				'secret'   => $secret,
				'response' => mep_eventi_field( 'cf-turnstile-response' ),
				'remoteip' => mep_eventi_client_ip(),
			),
		) );
		$ok = ! is_wp_error( $resp ) && ! empty( json_decode( wp_remote_retrieve_body( $resp ), true )['success'] );
		if ( ! $ok ) {
			mep_eventi_redirect( $back, 'spam' );
		}
	}
	$rk    = 'mep_ev_rl_' . md5( mep_eventi_client_ip() );
	$count = (int) get_transient( $rk );
	if ( $count >= (int) mep_eventi_opt( 'rate_per_hour' ) ) {
		mep_eventi_redirect( $back, 'troppi' );
	}

	// --- campi
	$f = array(
		'titolo'      => mep_eventi_field( 'mep_titolo' ),
		'data_inizio' => mep_eventi_field( 'mep_data_inizio' ),
		'ora_inizio'  => mep_eventi_field( 'mep_ora_inizio' ),
		'data_fine'   => mep_eventi_field( 'mep_data_fine' ),
		'ora_fine'    => mep_eventi_field( 'mep_ora_fine' ),
		'descrizione' => mep_eventi_field( 'mep_descrizione', 'textarea' ),
		'costo'       => mep_eventi_field( 'mep_costo' ),
		'link'        => mep_eventi_field( 'mep_link', 'url' ),
		'comune'      => mep_eventi_field( 'mep_comune' ),
		'luogo'       => mep_eventi_field( 'mep_luogo' ),
		'indirizzo'   => mep_eventi_field( 'mep_indirizzo' ),
		'org'         => mep_eventi_field( 'mep_org' ),
		'org_tel'     => mep_eventi_field( 'mep_org_tel' ),
		'org_email'   => mep_eventi_field( 'mep_org_email', 'email' ),
		'nome'        => mep_eventi_field( 'mep_nome' ),
		'email'       => mep_eventi_field( 'mep_email', 'email' ),
		'categoria'   => (int) mep_eventi_field( 'mep_categoria' ),
	);
	if ( empty( $_POST['mep_privacy'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
		mep_eventi_redirect( $back, 'privacy' );
	}
	foreach ( array( 'titolo', 'data_inizio', 'descrizione', 'comune', 'nome', 'email' ) as $req ) {
		if ( '' === $f[ $req ] ) {
			mep_eventi_redirect( $back, 'campi' );
		}
	}
	if ( ! is_email( $f['email'] ) ) {
		mep_eventi_redirect( $back, 'email' );
	}

	// --- date
	$tz    = wp_timezone();
	$valid = function ( $d ) {
		return (bool) preg_match( '/^\d{4}-\d{2}-\d{2}$/', $d );
	};
	$vt    = function ( $t ) {
		return (bool) preg_match( '/^\d{2}:\d{2}$/', $t );
	};
	if ( ! $valid( $f['data_inizio'] ) || ( $f['data_fine'] && ! $valid( $f['data_fine'] ) ) ) {
		mep_eventi_redirect( $back, 'data' );
	}
	$all_day = ! $vt( $f['ora_inizio'] );
	$end_day = $f['data_fine'] ? $f['data_fine'] : $f['data_inizio'];
	try {
		$start = new DateTime( $f['data_inizio'] . ' ' . ( $all_day ? '00:00' : $f['ora_inizio'] ), $tz );
		if ( $all_day ) {
			$end = new DateTime( $end_day . ' 23:59:59', $tz );
		} elseif ( $vt( $f['ora_fine'] ) ) {
			$end = new DateTime( $end_day . ' ' . $f['ora_fine'], $tz );
			if ( $end <= $start ) {
				$end->modify( '+1 day' );
			}
		} else {
			$end = ( clone $start )->modify( '+2 hours' );
			if ( $end_day !== $f['data_inizio'] ) {
				$end = new DateTime( $end_day . ' ' . $end->format( 'H:i' ), $tz );
			}
		}
	} catch ( Exception $e ) {
		mep_eventi_redirect( $back, 'data' );
	}
	$today = new DateTime( 'today', $tz );
	if ( $end < $today || $end < $start || $start > ( clone $today )->modify( '+2 years' ) ) {
		mep_eventi_redirect( $back, 'data' );
	}

	// --- locandina (controllo prima di creare l'evento)
	$has_file = ! empty( $_FILES['mep_locandina']['name'] ) && UPLOAD_ERR_NO_FILE !== (int) $_FILES['mep_locandina']['error']; // phpcs:ignore WordPress.Security.NonceVerification
	if ( $has_file ) {
		$file = $_FILES['mep_locandina']; // phpcs:ignore WordPress.Security.NonceVerification, WordPress.Security.ValidatedSanitizedInput
		$max  = (int) mep_eventi_opt( 'max_upload_mb' ) * MB_IN_BYTES;
		$chk  = wp_check_filetype_and_ext( $file['tmp_name'], $file['name'], array(
			'jpg|jpeg|jpe' => 'image/jpeg',
			'png'          => 'image/png',
			'webp'         => 'image/webp',
			'pdf'          => 'application/pdf',
		) );
		if ( UPLOAD_ERR_OK !== (int) $file['error'] || $file['size'] > $max || empty( $chk['type'] ) ) {
			mep_eventi_redirect( $back, 'file' );
		}
	}

	// --- creazione bozza
	$content = wpautop( esc_html( $f['descrizione'] ) );
	$info    = array();
	if ( $f['link'] ) {
		$info[] = '<li>Info: <a href="' . esc_url( $f['link'] ) . '" target="_blank" rel="noopener nofollow">' . esc_html( $f['link'] ) . '</a></li>';
	}
	if ( $f['org'] || $f['org_tel'] || $f['org_email'] ) {
		$info[] = '<li>Organizza: ' . esc_html( trim( implode( ' – ', array_filter( array( $f['org'], $f['org_tel'], $f['org_email'] ) ) ) ) ) . '</li>';
	}
	if ( $info ) {
		$content .= "\n<ul>" . implode( '', $info ) . '</ul>';
	}

	$event_id = mep_eventi_create_event( $f, $content, $start, $end, $all_day );
	if ( ! $event_id || is_wp_error( $event_id ) ) {
		mep_eventi_redirect( $back, 'errore' );
	}

	update_post_meta( $event_id, '_mep_segnalazione', 1 );
	update_post_meta( $event_id, '_mep_segnalato_nome', $f['nome'] );
	update_post_meta( $event_id, '_mep_segnalato_email', $f['email'] );
	update_post_meta( $event_id, '_mep_segnalato_il', current_time( 'mysql' ) );

	if ( $f['categoria'] && term_exists( $f['categoria'], 'tribe_events_cat' ) ) {
		wp_set_object_terms( $event_id, array( $f['categoria'] ), 'tribe_events_cat', false );
	}
	$tags = array_filter( array( mep_eventi_opt( 'reader_tag' ), $f['comune'] ) );
	if ( $tags ) {
		wp_set_post_terms( $event_id, $tags, 'post_tag', true );
	}

	if ( $has_file ) {
		require_once ABSPATH . 'wp-admin/includes/file.php';
		require_once ABSPATH . 'wp-admin/includes/media.php';
		require_once ABSPATH . 'wp-admin/includes/image.php';
		$att = media_handle_upload( 'mep_locandina', $event_id, array( 'post_title' => 'Locandina: ' . $f['titolo'] ) );
		if ( ! is_wp_error( $att ) ) {
			update_post_meta( $att, '_wp_attachment_image_alt', 'Locandina: ' . $f['titolo'] );
			if ( wp_attachment_is_image( $att ) ) {
				set_post_thumbnail( $event_id, $att );
			} else {
				// PDF: link nel testo; se WordPress ha creato l'anteprima la usiamo come immagine
				$pdf_url = wp_get_attachment_url( $att );
				wp_update_post( array(
					'ID'           => $event_id,
					'post_content' => $content . "\n<p><a href=\"" . esc_url( $pdf_url ) . '" target="_blank" rel="noopener">Scarica la locandina (PDF)</a></p>',
				) );
			}
		}
	}

	set_transient( $rk, $count + 1, HOUR_IN_SECONDS );
	mep_eventi_notify( $event_id, $f, $start );
	mep_eventi_redirect( $back, 'ok' );
}

/**
 * Crea l'evento in bozza con l'ORM di The Events Calendar (gestisce anche le tabelle personalizzate di TEC 6).
 * Se l'ORM non c'è, ripiega su wp_insert_post + meta: la bozza va comunque riaperta e salvata dalla redazione.
 */
function mep_eventi_create_event( $f, $content, DateTime $start, DateTime $end, $all_day ) {
	$tzs   = wp_timezone_string();
	$venue = 0;
	$org   = 0;
	$vname = $f['luogo'] ? $f['luogo'] : $f['comune'];

	if ( function_exists( 'tribe_venues' ) ) {
		try {
			$existing = get_posts( array(
				'post_type'   => 'tribe_venue',
				'title'       => $vname,
				'post_status' => array( 'publish', 'draft' ),
				'numberposts' => 5,
			) );
			foreach ( $existing as $v ) {
				if ( 0 === strcasecmp( (string) get_post_meta( $v->ID, '_VenueCity', true ), $f['comune'] ) ) {
					$venue = $v->ID;
					break;
				}
			}
			if ( ! $venue ) {
				$v = tribe_venues()->set_args( array(
					'title'    => $vname,
					'status'   => 'draft',
					'address'  => $f['indirizzo'],
					'city'     => $f['comune'],
					'country'  => 'Italia',
				) )->create();
				$venue = $v instanceof WP_Post ? $v->ID : 0;
			}
		} catch ( Throwable $e ) {
			$venue = 0;
		}
	}
	if ( $f['org'] && function_exists( 'tribe_organizers' ) ) {
		try {
			$o = tribe_organizers()->set_args( array(
				'title'  => $f['org'],
				'status' => 'draft',
				'phone'  => $f['org_tel'],
				'email'  => $f['org_email'],
			) )->create();
			$org = $o instanceof WP_Post ? $o->ID : 0;
		} catch ( Throwable $e ) {
			$org = 0;
		}
	}

	if ( function_exists( 'tribe_events' ) ) {
		try {
			$args = array(
				'title'       => $f['titolo'],
				'description' => $content,
				'status'      => 'draft',
				'start_date'  => $start->format( 'Y-m-d H:i:s' ),
				'end_date'    => $end->format( 'Y-m-d H:i:s' ),
				'timezone'    => $tzs,
				'all_day'     => $all_day,
			);
			if ( $venue ) {
				$args['venue'] = $venue;
			}
			if ( $org ) {
				$args['organizer'] = $org;
			}
			if ( $f['costo'] ) {
				$args['cost'] = $f['costo'];
			}
			if ( $f['link'] ) {
				$args['url'] = $f['link'];
			}
			$ev = tribe_events()->set_args( $args )->create();
			if ( $ev instanceof WP_Post ) {
				return $ev->ID;
			}
		} catch ( Throwable $e ) {
			// ripiego sotto
		}
	}

	$id = wp_insert_post( array(
		'post_type'    => 'tribe_events',
		'post_status'  => 'draft',
		'post_title'   => $f['titolo'],
		'post_content' => $content,
	), true );
	if ( is_wp_error( $id ) ) {
		return $id;
	}
	$utc = new DateTimeZone( 'UTC' );
	$meta = array(
		'_EventStartDate'    => $start->format( 'Y-m-d H:i:s' ),
		'_EventEndDate'      => $end->format( 'Y-m-d H:i:s' ),
		'_EventStartDateUTC' => ( clone $start )->setTimezone( $utc )->format( 'Y-m-d H:i:s' ),
		'_EventEndDateUTC'   => ( clone $end )->setTimezone( $utc )->format( 'Y-m-d H:i:s' ),
		'_EventDuration'     => $end->getTimestamp() - $start->getTimestamp(),
		'_EventTimezone'     => $tzs,
		'_EventCost'         => $f['costo'],
		'_EventURL'          => $f['link'],
	);
	if ( $all_day ) {
		$meta['_EventAllDay'] = 'yes';
	}
	if ( $venue ) {
		$meta['_EventVenueID'] = $venue;
	}
	if ( $org ) {
		$meta['_EventOrganizerID'] = $org;
	}
	foreach ( $meta as $k => $v ) {
		update_post_meta( $id, $k, $v );
	}
	return $id;
}

function mep_eventi_notify( $event_id, $f, DateTime $start ) {
	$to   = mep_eventi_opt( 'notify_email' );
	$edit = admin_url( 'post.php?post=' . (int) $event_id . '&action=edit' );
	$when = wp_date( 'l j F Y', $start->getTimestamp() );
	if ( $to ) {
		$body  = "Nuova segnalazione di evento dal sito.\n\n";
		$body .= 'Titolo: ' . $f['titolo'] . "\n";
		$body .= 'Quando: ' . $when . ( $f['ora_inizio'] ? ' ore ' . $f['ora_inizio'] : '' ) . "\n";
		$body .= 'Dove: ' . trim( $f['luogo'] . ', ' . $f['comune'], ', ' ) . "\n";
		$body .= 'Segnalato da: ' . $f['nome'] . ' <' . $f['email'] . ">\n\n";
		$body .= "Controlla e pubblica la bozza:\n" . $edit . "\n";
		wp_mail( $to, '[Montagne & Paesi] Nuovo evento segnalato: ' . $f['titolo'], $body, array( 'Reply-To: ' . $f['nome'] . ' <' . $f['email'] . '>' ) );
	}
	if ( mep_eventi_opt( 'notify_submitter' ) ) {
		$body  = 'Ciao ' . $f['nome'] . ",\n\n";
		$body .= 'abbiamo ricevuto la segnalazione di "' . $f['titolo'] . '" (' . $when . ").\n";
		$body .= "La redazione la controllerà a breve e, se adatta, la pubblicherà nel calendario eventi di Montagne & Paesi.\n\n";
		$body .= "Grazie!\nLa redazione di Montagne & Paesi\n" . home_url( '/' );
		wp_mail( $f['email'], 'Abbiamo ricevuto il tuo evento: ' . $f['titolo'], $body );
	}
}

/* -------------------------------------------------------------------------
 * Amministrazione: contatore segnalazioni e box con i dati del segnalatore
 * ---------------------------------------------------------------------- */

function mep_eventi_pending_count() {
	$q = new WP_Query( array(
		'post_type'      => 'tribe_events',
		'post_status'    => array( 'draft', 'pending' ),
		'meta_key'       => '_mep_segnalazione', // phpcs:ignore WordPress.DB.SlowDBQuery
		'fields'         => 'ids',
		'posts_per_page' => 1,
		'no_found_rows'  => false,
	) );
	return (int) $q->found_posts;
}

add_action( 'admin_menu', function () {
	global $menu;
	if ( ! current_user_can( 'edit_posts' ) || ! is_array( $menu ) ) {
		return;
	}
	$n = mep_eventi_pending_count();
	if ( ! $n ) {
		return;
	}
	foreach ( $menu as $i => $item ) {
		if ( isset( $item[2] ) && 'edit.php?post_type=tribe_events' === $item[2] ) {
			$menu[ $i ][0] .= ' <span class="awaiting-mod"><span class="pending-count">' . $n . '</span></span>'; // phpcs:ignore WordPress.WP.GlobalVariablesOverride
		}
	}
}, 99 );

add_filter( 'views_edit-tribe_events', function ( $views ) {
	$n   = mep_eventi_pending_count();
	$url = admin_url( 'edit.php?post_type=tribe_events&post_status=draft&mep_segnalazioni=1' );
	$cur = ! empty( $_GET['mep_segnalazioni'] ) ? ' class="current"' : ''; // phpcs:ignore WordPress.Security.NonceVerification
	$views['mep'] = '<a href="' . esc_url( $url ) . '"' . $cur . '>Segnalati dai lettori <span class="count">(' . $n . ')</span></a>';
	return $views;
} );

add_action( 'pre_get_posts', function ( $q ) {
	if ( is_admin() && $q->is_main_query() && ! empty( $_GET['mep_segnalazioni'] ) && 'tribe_events' === $q->get( 'post_type' ) ) { // phpcs:ignore WordPress.Security.NonceVerification
		$q->set( 'meta_key', '_mep_segnalazione' );
	}
} );

add_action( 'add_meta_boxes_tribe_events', function ( $post ) {
	if ( ! get_post_meta( $post->ID, '_mep_segnalazione', true ) ) {
		return;
	}
	add_meta_box( 'mep_segnalazione', 'Segnalazione del lettore', function ( $post ) {
		$nome  = get_post_meta( $post->ID, '_mep_segnalato_nome', true );
		$email = get_post_meta( $post->ID, '_mep_segnalato_email', true );
		$il    = get_post_meta( $post->ID, '_mep_segnalato_il', true );
		echo '<p><strong>' . esc_html( $nome ) . '</strong><br><a href="mailto:' . esc_attr( $email ) . '">' . esc_html( $email ) . '</a><br><span class="description">' . esc_html( $il ) . '</span></p>';
		echo '<p class="description">Dati non pubblicati. Controlla date, luogo e testo prima di pubblicare.</p>';
	}, null, 'side', 'high' );
} );
