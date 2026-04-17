declare const _default: {
    content: string[];
    theme: {
        extend: {
            colors: {
                ink: string;
                "ink-2": string;
                "ink-3": string;
                graphite: string;
                panel: string;
                ember: string;
                "ember-soft": string;
                neon: string;
                "neon-soft": string;
                storm: string;
                signal: string;
                "border-subtle": string;
                "border-strong": string;
            };
            boxShadow: {
                glow: string;
                "elev-1": string;
                "elev-2": string;
                "rail-glow": string;
                "hero-ring": string;
            };
            fontFamily: {
                sans: [string, string, string, string];
                mono: [string, string, string];
            };
            backgroundImage: {
                "command-grid": string;
                "soft-grid": string;
                "hairline-ring": string;
                "brand-aurora": string;
            };
            animation: {
                pulseLine: string;
                shimmer: string;
                pulseDot: string;
            };
            keyframes: {
                pulseLine: {
                    "0%, 100%": {
                        opacity: string;
                        transform: string;
                    };
                    "50%": {
                        opacity: string;
                        transform: string;
                    };
                };
                shimmer: {
                    "0%": {
                        backgroundPosition: string;
                    };
                    "100%": {
                        backgroundPosition: string;
                    };
                };
                pulseDot: {
                    "0%, 100%": {
                        opacity: string;
                        transform: string;
                    };
                    "50%": {
                        opacity: string;
                        transform: string;
                    };
                };
            };
        };
    };
    plugins: any[];
};
export default _default;
