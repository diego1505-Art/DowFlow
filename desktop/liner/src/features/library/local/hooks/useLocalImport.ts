import { useCallback } from "react";
import { useTranslation } from "@/languages";
import { showToast } from "@/shared/ui";
import type { LocalImportResult } from "@/shared/media/local";
import { useLocalLibraryStore } from "../store/localLibraryStore";

type Translate = ReturnType<typeof useTranslation>["t"];

function announce(result: LocalImportResult | null, t: Translate) {
  if (!result) return;
  const { added, duplicates, failed } = result;
  if (added.length > 0) {
    showToast(
      t("library.local.imported", { count: added.length }),
      "checkmark",
      {
        description:
          duplicates > 0
            ? t("library.local.skipped_duplicates", { count: duplicates })
            : added.length === 1
              ? added[0].title
              : undefined,
      },
    );
  } else if (duplicates > 0 && failed.length === 0) {
    showToast(t("library.local.already_added"), "info");
  }
  if (failed.length > 0) {
    showToast(
      t("library.local.import_failed", { count: failed.length }),
      "error",
      {
        description: failed.slice(0, 3).join(", "),
      },
    );
  }
}

export function useLocalImport() {
  const { t } = useTranslation();
  const importPaths = useLocalLibraryStore((state) => state.importPaths);
  const pickFiles = useLocalLibraryStore((state) => state.pickFiles);
  const importing = useLocalLibraryStore((state) => state.importing);

  const importFiles = useCallback(
    async (files: File[]) => {
      const bridge = window.linerElectron;
      if (!bridge) return;
      const paths = files
        .map((file) => bridge.pathForFile(file))
        .filter(Boolean);
      announce(await importPaths(paths), t);
    },
    [importPaths, t],
  );

  const chooseFiles = useCallback(async () => {
    announce(await pickFiles(), t);
  }, [pickFiles, t]);

  return { importFiles, chooseFiles, importing };
}
