import { FullSlug, isFolderPath, resolveRelative } from "../util/path"
import { QuartzPluginData } from "../plugins/vfile"
import { Date, getDate } from "./Date"
import { QuartzComponent, QuartzComponentProps } from "./types"

export type SortFn = (f1: QuartzPluginData, f2: QuartzPluginData) => number

export function byDateAndAlphabetical(): SortFn {
  return (f1, f2) => {
    // 1. Sort by frontmatter / plugin dates (descending: newest first)
    if (f1.dates && f2.dates) {
      const d1 = getDate(f1)?.getTime() ?? 0
      const d2 = getDate(f2)?.getTime() ?? 0
      if (d1 !== d2) {
        return d2 - d1
      }
    } else if (f1.dates && !f2.dates) {
      return -1
    } else if (!f1.dates && f2.dates) {
      return 1
    }

    // 2. Extract timestamp from filename or slug (e.g. 20260817_0724 or 20260817)
    const match1 = (f1.slug ?? "").match(/\d{8}(?:_\d{4})?/)
    const match2 = (f2.slug ?? "").match(/\d{8}(?:_\d{4})?/)
    if (match1 && match2 && match1[0] !== match2[0]) {
      return match2[0].localeCompare(match1[0]) // Descending
    }
    if (match1 && !match2) return -1
    if (!match1 && match2) return 1

    // otherwise, sort lexographically by title
    const f1Title = f1.frontmatter?.title.toLowerCase() ?? ""
    const f2Title = f2.frontmatter?.title.toLowerCase() ?? ""
    return f1Title.localeCompare(f2Title)
  }
}

export function byDateAndAlphabeticalFolderFirst(): SortFn {
  return (f1, f2) => {
    // Sort folders first
    const f1IsFolder = isFolderPath(f1.slug ?? "")
    const f2IsFolder = isFolderPath(f2.slug ?? "")
    if (f1IsFolder && !f2IsFolder) return -1
    if (!f1IsFolder && f2IsFolder) return 1

    // 1. Sort by frontmatter / plugin dates (descending: newest first)
    if (f1.dates && f2.dates) {
      const d1 = getDate(f1)?.getTime() ?? 0
      const d2 = getDate(f2)?.getTime() ?? 0
      if (d1 !== d2) {
        return d2 - d1
      }
    } else if (f1.dates && !f2.dates) {
      return -1
    } else if (!f1.dates && f2.dates) {
      return 1
    }

    // 2. Extract timestamp from filename or slug (e.g. 20260817_0724 or 20260817)
    const match1 = (f1.slug ?? "").match(/\d{8}(?:_\d{4})?/)
    const match2 = (f2.slug ?? "").match(/\d{8}(?:_\d{4})?/)
    if (match1 && match2 && match1[0] !== match2[0]) {
      return match2[0].localeCompare(match1[0]) // Descending
    }
    if (match1 && !match2) return -1
    if (!match1 && match2) return 1

    // otherwise, sort lexographically by title
    const f1Title = f1.frontmatter?.title.toLowerCase() ?? ""
    const f2Title = f2.frontmatter?.title.toLowerCase() ?? ""
    return f1Title.localeCompare(f2Title)
  }
}

type Props = {
  limit?: number
  sort?: SortFn
} & QuartzComponentProps

export const PageList: QuartzComponent = ({ cfg, fileData, allFiles, limit, sort }: Props) => {
  const sorter = sort ?? byDateAndAlphabeticalFolderFirst()
  let list = allFiles.sort(sorter)
  if (limit) {
    list = list.slice(0, limit)
  }

  return (
    <ul class="section-ul">
      {list.map((page) => {
        const title = page.frontmatter?.title
        const tags = page.frontmatter?.tags ?? []

        return (
          <li class="section-li">
            <div class="section">
              <p class="meta">{page.dates && <Date date={getDate(page)!} locale={cfg.locale} />}</p>
              <div class="desc">
                <h3>
                  <a
                    href={resolveRelative(fileData.slug!, page.slug!)}
                    class="internal internal-link"
                  >
                    {title}
                  </a>
                </h3>
              </div>
              <ul class="tags">
                {tags.map((tag) => (
                  <li>
                    <a
                      class="internal tag-link"
                      href={resolveRelative(fileData.slug!, `tags/${tag}` as FullSlug)}
                    >
                      {tag}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

PageList.css = `
.section h3 {
  margin: 0;
}

.section > .tags {
  margin: 0;
}
`
