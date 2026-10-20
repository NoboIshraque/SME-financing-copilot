// Settings: who you are and your access, language, theme, notification opt-ins (auto-send is the
// owner's call), data mode, and the API mode switch in development builds only.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { API_MODES, readSavedApiMode, resolveApiMode, saveApiMode, type ApiMode } from "../../api/apiMode";
import { ApiRequestError } from "../../api/client";
import { api } from "../../api/endpoints";
import type { UserSettings } from "../../api/types";
import { useRequiredSession } from "../../auth/session";
import { LanguageSwitcher } from "../../components/LanguageSwitcher";
import { ErrorState, QueryView } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useFormat } from "../../i18n/useFormat";
import { THEMES, setThemePreference, useThemePreference } from "../../theme";

const card = "rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800";

function Notifications({ initial }: { initial: UserSettings }) {
  const { t } = useTranslation();
  const session = useRequiredSession();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(initial);
  const save = useMutation({
    mutationFn: (next: UserSettings) => api.settings.save(next),
    onSuccess: (saved) => queryClient.setQueryData(["settings"], saved),
  });
  const owner = session.principal.role === "owner";
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(draft);
      }}
      className="space-y-2"
    >
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={draft.auto_send_reminders} disabled={!owner} onChange={(e) => setDraft({ ...draft, auto_send_reminders: e.target.checked })} className="mt-1 accent-teal-700" />
        <span>
          {t("settings.autoSend")}
          <span className="block text-xs text-slate-500 dark:text-slate-400">{owner ? t("settings.autoSendHelp") : t("settings.ownerOnly")}</span>
        </span>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={draft.email_alerts} onChange={(e) => setDraft({ ...draft, email_alerts: e.target.checked })} className="accent-teal-700" />
        {t("settings.emailAlerts")}
      </label>
      <button type="submit" disabled={save.isPending} className="rounded-xl bg-teal-700 px-4 py-2.5 font-semibold text-white disabled:opacity-60">
        {t("settings.save")}
      </button>
      {save.isSuccess && <p className="text-sm text-emerald-700 dark:text-emerald-300">{t("settings.saved")}</p>}
      {save.isError && <ErrorState error={save.error} />}
    </form>
  );
}

export function SettingsScreen() {
  const { t } = useTranslation();
  const format = useFormat();
  useDocumentTitle(t("nav.settings"));
  const session = useRequiredSession();
  const theme = useThemePreference();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings.get, enabled: session.principal.role !== "lender_viewer" });
  // Settings storage has no backend router (sending channels were cut): hide the card instead of
  // showing an error when the server has no such route.
  const noSettingsRoute = settings.error instanceof ApiRequestError && settings.error.body === null && settings.error.status === 404;
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 10 * 60_000 });
  const [apiMode, setApiMode] = useState<ApiMode>(() => resolveApiMode(import.meta.env, readSavedApiMode()));
  const { principal } = session;

  return (
    <section aria-labelledby="h-settings" className="space-y-6">
      <h2 id="h-settings" className="text-xl font-semibold">{t("nav.settings")}</h2>

      <section aria-labelledby="h-profile" className={card}>
        <h3 id="h-profile" className="text-lg font-semibold">{t("settings.profile")}</h3>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt className="text-slate-600 dark:text-slate-400">{t("settings.name")}</dt>
          <dd>{session.display_name}</dd>
          <dt className="text-slate-600 dark:text-slate-400">{t("settings.role")}</dt>
          <dd>{t(`role.${principal.role}`)}</dd>
          <dt className="text-slate-600 dark:text-slate-400">{t("settings.business")}</dt>
          <dd>{session.business_name}</dd>
          <dt className="text-slate-600 dark:text-slate-400">{t("settings.twoStep")}</dt>
          <dd>{session.totp_enrolled ? t("settings.twoStepOn") : t("settings.twoStepOff")}</dd>
          {principal.expires_at && (
            <>
              <dt className="text-slate-600 dark:text-slate-400">{t("settings.accessUntil")}</dt>
              <dd>{format.date(principal.expires_at, "long")}</dd>
            </>
          )}
        </dl>
      </section>

      <section aria-labelledby="h-display" className={card}>
        <h3 id="h-display" className="text-lg font-semibold">{t("settings.display")}</h3>
        <div className="mt-2 flex items-center gap-3 text-sm">
          <span>{t("language.label")}</span>
          <LanguageSwitcher />
        </div>
        <fieldset className="mt-3">
          <legend className="text-sm font-medium">{t("settings.theme")}</legend>
          <div className="mt-1 flex flex-wrap gap-4">
            {THEMES.map((choice) => (
              <label key={choice} className="flex items-center gap-2 text-sm">
                <input type="radio" name="theme" value={choice} checked={theme === choice} onChange={() => setThemePreference(choice)} className="accent-teal-700" />
                {t(`settings.themes.${choice}`)}
              </label>
            ))}
          </div>
        </fieldset>
      </section>

      {principal.role !== "lender_viewer" && !noSettingsRoute && (
        <section aria-labelledby="h-notify" className={card}>
          <h3 id="h-notify" className="text-lg font-semibold">{t("settings.notifications")}</h3>
          <QueryView query={settings}>{(data) => <Notifications initial={data} />}</QueryView>
        </section>
      )}

      <section aria-labelledby="h-data" className={card}>
        <h3 id="h-data" className="text-lg font-semibold">{t("settings.data")}</h3>
        <p className="mt-1 text-sm">{t(`dataMode.${session.data_mode}`)}</p>
        {health.data && <p className="text-xs text-slate-500 dark:text-slate-400">{t("settings.contracts", { version: health.data.contracts_version })}</p>}
        {import.meta.env.DEV && (
          <label className="mt-3 flex items-center gap-2 text-sm">
            {t("settings.apiMode")}
            <select
              value={apiMode}
              onChange={(event) => {
                const mode = event.target.value as ApiMode;
                setApiMode(mode);
                saveApiMode(mode);
              }}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            >
              {API_MODES.map((mode) => <option key={mode} value={mode}>{t(`settings.apiModes.${mode}`)}</option>)}
            </select>
            <span className="text-xs text-slate-500 dark:text-slate-400">{t("settings.reloadNeeded")}</span>
          </label>
        )}
      </section>
    </section>
  );
}
