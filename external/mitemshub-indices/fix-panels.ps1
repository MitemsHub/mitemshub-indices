$files = Get-ChildItem "src\components\intelligence\*.tsx"
foreach ($f in $files) {
    $c = Get-Content $f.FullName -Raw
    # Fix "use client" directive
    $c = $c -replace '^"use client";', '"use client"'
    # Ensure React import is present
    if ($c -notmatch '^import React from "react"') {
        $c = 'import React from "react";`n' + $c
    }
    Set-Content $f.FullName $c -Encoding UTF8
    Write-Host "Fixed $($f.Name)"
}