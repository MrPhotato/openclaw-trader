declare const _default: {
    content: string[];
    theme: {
        extend: {
            colors: {
                ink: string;
                panel: string;
                ember: string;
                neon: string;
                storm: string;
                signal: string;
            };
            boxShadow: {
                glow: string;
            };
            fontFamily: {
                sans: [string, string, string, string];
                mono: [string, string, string];
            };
            backgroundImage: {
                "command-grid": string;
            };
            animation: {
                pulseLine: string;
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
            };
        };
    };
    plugins: any[];
};
export default _default;
