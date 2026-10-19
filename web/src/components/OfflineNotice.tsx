// Shown while the device is offline: the installed app shell still opens, but numbers need the
// server (API answers are deliberately never cached).
import { useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

export function OfflineNotice() {
  const { t } = useTranslation();
  const online = useSyncExternalStore(subscribe, () => navigator.onLine, () => true);
  if (online) return null;
  return (
    <p aria-live="polite" className="bg-slate-800 px-4 py-2 text-center text-sm text-white">
      {t("shell.offline")}
    </p>
  );
}
