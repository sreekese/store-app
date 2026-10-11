// Decorative artwork, not inventory, an advertisement, or a claimable offer.
export default function NeighbourhoodArt() {
  return (
    <div className="neighbourhood-art" aria-hidden="true">
      <span className="art-orbit orbit-one" />
      <span className="art-orbit orbit-two" />
      <div className="art-location">⌖ A little closer to local</div>
      <svg viewBox="0 0 500 360" focusable="false">
        <ellipse
          cx="255"
          cy="315"
          rx="212"
          ry="22"
          fill="#174f46"
          opacity=".1"
        />
        <circle cx="377" cy="70" r="39" fill="#e8f38c" />
        <path
          d="M40 309h425"
          stroke="#174f46"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <g transform="translate(60 116) rotate(-7 86 100)">
          <rect
            width="156"
            height="182"
            rx="10"
            fill="#f2b795"
            stroke="#174f46"
            strokeWidth="3"
          />
          <rect x="17" y="18" width="122" height="29" rx="5" fill="#fffaf0" />
          <text
            x="78"
            y="38"
            textAnchor="middle"
            fill="#174f46"
            fontSize="16"
            fontWeight="700"
          >
            THE CORNER
          </text>
          <path d="M-9 64h174l-12-23H3z" fill="#174f46" />
          <path
            d="M-9 64v20q14 17 29 0 14 17 29 0 14 17 29 0 14 17 29 0 14 17 29 0 14 17 29 0V64"
            fill="#fffaf0"
            stroke="#174f46"
            strokeWidth="3"
          />
          <rect x="17" y="103" width="48" height="79" rx="4" fill="#174f46" />
          <rect
            x="82"
            y="103"
            width="55"
            height="50"
            rx="4"
            fill="#fffaf0"
            stroke="#174f46"
            strokeWidth="3"
          />
          <circle cx="53" cy="144" r="3" fill="#e8f38c" />
          <path
            d="M98 137v-15h22v15q-11 12-22 0m22-12q13-1 8 8h-8"
            fill="none"
            stroke="#174f46"
            strokeWidth="3"
          />
        </g>
        <g transform="translate(235 84) rotate(5 89 100)">
          <rect
            x="0"
            y="0"
            width="178"
            height="224"
            rx="12"
            fill="#dbe9b5"
            stroke="#174f46"
            strokeWidth="3"
          />
          <rect x="20" y="17" width="138" height="32" rx="5" fill="#174f46" />
          <text
            x="89"
            y="39"
            textAnchor="middle"
            fill="#fffaf0"
            fontSize="17"
            fontWeight="700"
          >
            GOOD FINDS
          </text>
          <path
            d="M-9 70h196l-12-20H3z"
            fill="#fffaf0"
            stroke="#174f46"
            strokeWidth="3"
          />
          <path
            d="M-9 70v18q16 18 33 0 16 18 33 0 16 18 33 0 16 18 33 0 16 18 32 0 16 18 32 0V70"
            fill="#174f46"
          />
          <rect
            x="20"
            y="113"
            width="75"
            height="77"
            rx="5"
            fill="#fffaf0"
            stroke="#174f46"
            strokeWidth="3"
          />
          <path
            d="m43 135 14-8 15 8 12 17-12 7v18H43v-18l-11-7z"
            fill="#e8b3cf"
            stroke="#174f46"
            strokeWidth="2"
          />
          <rect x="112" y="113" width="46" height="111" rx="4" fill="#174f46" />
          <circle cx="123" cy="166" r="3" fill="#e8f38c" />
        </g>
        <path d="M438 309v-70" stroke="#174f46" strokeWidth="5" />
        <ellipse cx="435" cy="229" rx="23" ry="33" fill="#174f46" />
        <path d="m33 106 6-16 6 16 16 6-16 6-6 16-6-16-16-6z" fill="#174f46" />
        <path d="m430 130 4-11 4 11 11 4-11 4-4 11-4-11-11-4z" fill="#f2b795" />
      </svg>
      <div className="art-caption">
        <span>✳</span>
        <div>
          Your next favourite?
          <br />
          <strong>Just around the corner.</strong>
        </div>
      </div>
    </div>
  );
}
