import { createContext, ReactNode, useContext, useState } from "react";

type Lang = "en" | "es";

const STRINGS: Record<Lang, Record<string, string>> = {
  en: {
    printers: "Printers",
    formats: "Document Formats",
    templates: "PDF Templates",
    overlays: "PDF Overlays",
    jobs: "Jobs",
    remote: "Remote Access",
    device: "Device",
    lock: "Lock",
    add_printer: "Add printer",
    discover: "Discover printers on the LAN",
    new_format: "New format",
    new_template: "New template",
    builder: "Builder",
    json: "JSON",
    save: "Save",
    name: "Name",
    type: "Type",
    create: "Create",
    delete: "Delete",
    test: "Test",
    live_preview: "Live preview",
    add_element: "Add element",
  },
  es: {
    printers: "Impresoras",
    formats: "Formatos de documento",
    templates: "Plantillas PDF",
    overlays: "Superposiciones PDF",
    jobs: "Trabajos",
    remote: "Acceso Remoto",
    device: "Dispositivo",
    lock: "Bloquear",
    add_printer: "Agregar impresora",
    discover: "Descubrir impresoras en la LAN",
    new_format: "Nuevo formato",
    new_template: "Nueva plantilla",
    builder: "Editor",
    json: "JSON",
    save: "Guardar",
    name: "Nombre",
    type: "Tipo",
    create: "Crear",
    delete: "Eliminar",
    test: "Prueba",
    live_preview: "Vista previa",
    add_element: "Agregar elemento",
  },
};

interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
}

const Ctx = createContext<I18n>({ lang: "en", setLang: () => {}, t: (k) => k });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(
    (localStorage.getItem("vibe_lang") as Lang) || "en",
  );
  const setLang = (l: Lang) => {
    localStorage.setItem("vibe_lang", l);
    setLangState(l);
  };
  const t = (key: string) => STRINGS[lang][key] ?? STRINGS.en[key] ?? key;
  return <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
